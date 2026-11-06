"""ShieldAI Executor - runs the first-principles plan, deterministically.

Every step is 100% local and verifiable:

  ingestion    -> pull local files referenced in the request (size-capped)
  extraction   -> agent-specific deterministic extractors (no LLM, no guessing)
  verification -> check each unknown against the source text; report
                  "evidence_found" / "evidence_missing" / "needs_human"
                  honestly (a pattern match is evidence, not proof)
  synthesis    -> compose the answer strictly from extracted evidence

If a medical request contains PHI-shaped patterns, execution is blocked
before extraction - the agent's own first principle, enforced in code.
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from guardian_ai.compliance import scan_sensitive
from guardian_ai.ollama_inference import OllamaClient

MAX_FILE_BYTES = 64 * 1024
MAX_FILES = 3
MAX_EXCERPTS = 5
EXCERPT_LEN = 160

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?\n])")
_DATE_RE = re.compile(r"(?:20\d{2}|令和\d+)\s*[年/-]\s*\d{1,2}\s*月?\s*\d{0,2}\s*日?|\d{4}-\d{2}-\d{2}")
_MONEY_RE = re.compile(r"[¥￥$]\s*[\d,]+|[\d,]+\s*円|\d+(?:\.\d+)?\s*%")

# Agent-specific extraction patterns: (kind, regex)
_AGENT_PATTERNS: Dict[str, List[Tuple[str, "re.Pattern"]]] = {
    "legal": [
        ("obligation", re.compile(r"すること|しなければ|禁止|義務|担保|保証|must|shall|agree|undertake", re.I)),
        ("party", re.compile(r"甲|乙|両者|当事者|party|between")),
        ("penalty", re.compile(r"違約|損害賠償|penalty|liquidated|fine", re.I)),
    ],
    "accounting": [
        ("figure", re.compile(r"[\d,]+\s*円|[¥￥]\s*[\d,]+|\d+(?:\.\d+)?\s*%")),
        ("period", re.compile(r"年度|会計期間|期末|決算|Q[1-4]| fiscal ", re.I)),
        ("account", re.compile(r"借方|貸方|資産|負債|収益|費用")),
    ],
    "it": [
        ("error", re.compile(r"ERROR|FATAL|CRITICAL|Exception|Traceback|タイムアウト|障害|failed", re.I)),
        ("timestamp", re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2}")),
        ("host", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.I)),
        ("http_status", re.compile(r"\b[1-5]\d{2}\b.*(?:status|code|response|HTTP)", re.I)),
    ],
    "developer": [
        ("code_block", re.compile(r"```")),
        ("file_ref", re.compile(r"[\w./-]+\.(?:py|js|ts|tsx|java|go|rs|cpp|cc|c|h|rb|php)\b")),
        ("line_ref", re.compile(r"[\w./-]+\.[a-z]+:\d+|line\s+\d+|行\s*\d+", re.I)),
        ("command", re.compile(r"\b(?:npm|pip|pytest|cargo|make|gradle|mvn|git)\b")),
    ],
    "hr": [
        ("experience", re.compile(r"\d+\s*年(?:\s*\d+\s*ヶ月)?|実務経験|開発経験")),
        ("skill", re.compile(r"スキル|資格|言語|framework", re.I)),
        ("claim", re.compile(r"担当|開発|設計|運用|保守")),
    ],
    "medical": [
        ("measurement", re.compile(r"\d+(?:\.\d+)?\s*(?:mg/dL|mmHg|bpm|℃|度|ml|kg)")),
        ("symptom", re.compile(r"症状|所見|検査|診断|治療|処方")),
    ],
    "general": [
        ("date", _DATE_RE),
        ("quantity", _MONEY_RE),
        ("contact", re.compile(r"\b\d{2,4}[-()]?\d{3,4}[-()]?\d{3,4}\b|[\w.+-]+@[\w-]+\.[\w.]+")),
    ],
}

# Unknown description -> (regex to look for in source, label)
_UNKNOWN_CHECKS: List[Tuple[str, "re.Pattern", str]] = [
    ("risk tolerance threshold", re.compile(r"閾値|threshold|許容|リスク.{0,10}\d", re.I), "risk threshold definition"),
    ("Time span and budget", re.compile(r"期間|予算|budget|deadline|納期|までに|以内|上限", re.I), "schedule/budget boundary"),
    ("Reproduction condition", re.compile(r"再現|手順|repro|steps?|発生条件|再起", re.I), "reproduction steps"),
    ("Correctness oracle", re.compile(r"テスト|test|期待|expected|合格|pass", re.I), "passing criteria"),
    ("valid contract document", re.compile(r"第\s*\d+\s*版|改訂|revision|ver\.?\s*\d|20\d{2}年.*版", re.I), "valid revision"),
    ("Dosage and unit", re.compile(r"\d+(?:\.\d+)?\s*(?:mg|ml|g|mcg|μg|単位|錠|cap|tablet)", re.I), "dosage units"),
    ("claimed experience", re.compile(r"\d+\s*年|証明|在籍|勤務|実績|experience", re.I), "experience record"),
    ("accounting standard", re.compile(r"GAAP|IFRS|JIS|基準|適用|期末|締め|closing|period", re.I), "accounting standard/period"),
    ("Definition of done", re.compile(r"完了|合格|成功|done|finish|complete|acceptance", re.I), "completion criterion"),
]


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _find_local_files(request: str, root: Optional[Path] = None) -> List[Path]:
    """Resolve local files referenced in the request.

    Direct paths are checked first; a bare filename (e.g. 'server.py') is
    then located under `root` via LocalSearch with the same exclusions.
    """
    from guardian_ai.local_search import LocalSearch

    root = Path(root) if root else Path.cwd()
    files: List[Path] = []
    seen = set()
    searcher = None
    for token in re.findall(r"[^\s\"'、。，,()（）「」『』]+", request):
        token = token.strip("<>[]{}:;|")
        if not token or "." not in token:
            continue
        p = Path(token)
        if not p.is_absolute():
            p = root / p
        try:
            if p.is_file() and 0 < p.stat().st_size <= MAX_FILE_BYTES:
                if p.resolve() not in seen:
                    files.append(p)
                    seen.add(p.resolve())
                continue
        except OSError:
            continue
        if token == os.path.basename(token):
            searcher = searcher or LocalSearch(str(root))
            for hit in searcher.find_file(token):
                hp = Path(hit)
                try:
                    ok = hp.is_file() and 0 < hp.stat().st_size <= MAX_FILE_BYTES
                except OSError:
                    ok = False
                if ok and hp.resolve() not in seen:
                    files.append(hp)
                    seen.add(hp.resolve())
                    break
        if len(files) >= MAX_FILES:
            break
    return files[:MAX_FILES]


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract(agent: str, corpus: str) -> List[Dict[str, str]]:
    """Deterministic extraction: sentences matching the agent's patterns."""
    patterns = _AGENT_PATTERNS.get(agent, _AGENT_PATTERNS["general"])
    findings: List[Dict[str, str]] = []
    for sentence in _sentences(corpus):
        for kind, pattern in patterns:
            if pattern.search(sentence):
                findings.append({"kind": kind, "text": sentence[:EXCERPT_LEN]})
                break
        if len(findings) >= MAX_EXCERPTS * 4:
            break
    # de-duplicate, keep order
    seen, unique = set(), []
    for f in findings:
        if f["text"] not in seen:
            seen.add(f["text"])
            unique.append(f)
    return unique[:MAX_EXCERPTS]


def _verify_unknowns(unknowns: List[str], corpus: str) -> List[Dict[str, str]]:
    """Check each unknown against the source text. Never fabricate."""
    results = []
    for unknown in unknowns:
        matched = None
        for key, pattern, label in _UNKNOWN_CHECKS:
            if key.lower() in unknown.lower() or key.split()[0].lower() in unknown.lower():
                matched = (pattern, label)
                break
        if matched is None:
            results.append({"unknown": unknown, "status": "needs_human",
                            "detail": "no deterministic check available; requester must define it"})
            continue
        pattern, label = matched
        hit = pattern.search(corpus)
        results.append({
            "unknown": unknown,
            "status": "evidence_found" if hit else "evidence_missing",
            "detail": f"{label}: {'found in source' if hit else 'not found in provided material'}",
        })
    return results


def _synthesize(agent: str, files: List[Path], evidence: List[Dict[str, str]],
                verification: List[Dict[str, str]]) -> str:
    lines = [f"[ShieldAI/{agent}] ローカル解析結果"]
    if files:
        lines.append(f"ソース: {', '.join(p.name for p in files)} ({len(files)} ファイル)")
    else:
        lines.append("ソース: リクエスト本文のみ (ファイル参照なし)")
    if evidence:
        kinds = {}
        for e in evidence:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        summary = ", ".join(f"{k}x{v}" for k, v in kinds.items())
        lines.append(f"抽出: {len(evidence)} 件 ({summary})")
        for e in evidence[:3]:
            lines.append(f"  - [{e['kind']}] {e['text']}")
        if len(evidence) > 3:
            lines.append(f"  - ... 他 {len(evidence) - 3} 件")
    else:
        lines.append("抽出: ソース内に agent 固有のパターンは検出されませんでした")
    found = sum(1 for v in verification if v["status"] == "evidence_found")
    lines.append(f"照合: unknowns {len(verification)} 件中 {found} 件に証拠パターンを検出")
    for v in verification:
        if v["status"] != "evidence_found":
            lines.append(f"  - [{v['status']}] {v['unknown']}")
    lines.append("注: 上記は決定論的ローカル処理のパターン照合結果です(検証ではありません)。")
    return "\n".join(lines)


_LLM_SYSTEM = (
    "あなたは ShieldAI のローカル合成エンジンです。"
    "提供された証拠だけに基づいて簡潔に答えてください。"
    "証拠にない事実を作ってはいけません。不明な点は『不明』と明記してください。")

_LLM_PROMPT = (
    "あなたのタスクは、提供された証拠のみに基づく要約です。\n\n"
    "依頼: {request}\n\n"
    "証拠 (ローカル抽出・パターン照合済):\n{evidence}\n\n"
    "未検証の項目:\n{unknowns}\n\n"
    "出力形式:\n"
    "- 箇条書きで最大3点\n"
    "- 各項目は1行\n"
    "- 証拠にない事実は絶対に書かない\n"
    "- 証拠が不足している点は『不足』と明記")


class Executor:
    """Executes a Router.analyze() result through the plan steps.

    A local Ollama daemon, when reachable, only fills in the synthesis step
    using extracted evidence - it never touches ingestion/extraction and its
    output is always labelled as model inference, not fact.
    """

    def __init__(self, llm: Optional[OllamaClient] = None,
                 search_root: Optional[str] = None):
        self.llm = llm if llm is not None else OllamaClient()
        self.search_root = search_root or os.getcwd()

    def _llm_synthesize(self, request: str, model: str,
                        evidence: List[Dict[str, str]],
                        verification: List[Dict[str, str]]) -> Optional[Tuple[str, str]]:
        """Best-effort local LLM synthesis. Returns (model, text) or None."""
        if not self.llm.available():
            return None
        chosen = self.llm.pick_model(model)
        if not chosen:
            return None
        ev = "\n".join(f"- [{e['kind']}] {e['text']}" for e in evidence[:8]) or "(証拠なし)"
        un = "\n".join(f"- {v['unknown']} ({v['status']})" for v in verification) or "(なし)"
        # CPU inference can take minutes on the first call (model load +
        # slow eval); a 300s cap keeps the CLI usable while still bounded.
        text = self.llm.generate(
            _LLM_PROMPT.format(request=request[:500], evidence=ev, unknowns=un),
            model=chosen, system=_LLM_SYSTEM, timeout=300)
        return (chosen, text.strip()) if text else None

    def execute(self, request: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        agent = analysis.get("agent", "general")
        thinking = analysis.get("thinking", {})
        unknowns = thinking.get("unknowns", [])
        steps: List[Dict[str, str]] = []

        # --- step 1: ingestion -------------------------------------------
        files = _find_local_files(request, self.search_root)
        corpus_parts = [request]
        read_files: List[Path] = []
        failed = []
        for p in files:
            try:
                corpus_parts.append(_read_text(p))
                read_files.append(p)
            except OSError:
                failed.append(p.name)
        corpus = "\n".join(corpus_parts)
        ing_status = "ok" if not failed else ("partial" if read_files else "fail")
        detail = f"{len(read_files)} file(s), {len(corpus)} chars"
        if failed:
            detail += f" (unreadable: {', '.join(failed)})"
        steps.append({"step": "ingestion", "status": ing_status,
                      "detail": detail})

        # --- secret gate (all agents) ------------------------------------
        # "Secrets are deleted, not processed" is a universal principle -
        # a credential pasted into ANY request must not reach extraction
        # or the LLM prompt, regardless of which agent was routed to.
        phi_hits = scan_sensitive(corpus)
        if phi_hits:
            return {
                "status": "blocked",
                "reason": f"secret patterns detected ({', '.join(phi_hits)}); "
                          "anonymize before processing",
                "steps": steps + [{"step": "extraction", "status": "blocked",
                                   "detail": "secret gate"}],
                "answer": "機密パターンを検出。匿名化してから再試行してください。処理をブロックしました。",
            }

        # --- step 2: extraction ------------------------------------------
        evidence = _extract(agent, corpus)
        steps.append({"step": "extraction", "status": "ok",
                      "detail": f"{len(evidence)} findings"})

        # --- step 3: verification ----------------------------------------
        verification = _verify_unknowns(unknowns, corpus)
        steps.append({"step": "verification", "status": "ok",
                      "detail": f"{sum(1 for v in verification if v['status'] == 'evidence_found')}/"
                                f"{len(verification)} evidence_found"})

        # --- step 4: synthesis -------------------------------------------
        answer = _synthesize(agent, read_files, evidence, verification)
        llm = self._llm_synthesize(
            request, analysis.get("model", ""), evidence, verification)
        llm_model = None
        if llm:
            llm_model, llm_text = llm
            answer += (f"\n\n[LLM 推論 ({llm_model}) - モデル生成・未検証]\n"
                       + llm_text)
            steps.append({"step": "synthesis", "status": "ok",
                          "detail": f"deterministic + llm({llm_model})"})
        else:
            steps.append({"step": "synthesis", "status": "ok",
                          "detail": "deterministic only (no local LLM)"})

        return {
            "status": "done",
            "answer": answer,
            "files": [str(p) for p in read_files],
            "evidence": evidence,
            "verification": verification,
            "steps": steps,
            "llm_model": llm_model,
        }


__all__ = ["Executor"]
