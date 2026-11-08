"""ShieldAI CLI - classify requests, execute first-principles plans, audit everything."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guardian_ai.compliance import audit_integrity, redact
from guardian_ai.db import (init_database, audit_log, export_audit,
                            record_tasks, verify_audit_chain)
from guardian_ai.executor import Executor
from guardian_ai.router import Router

# i18n: the CLI mirrors the web UI - banner/help live in a JA/EN dict,
# language resolves SHIELDAI_LANG -> --lang xx -> OS locale -> 'en'.
_CLI_STR = {
    "en": {"banner": """
==================================================
SHIELDAI - LOCAL AI CONTROL PLANE
==================================================
Type a request, or 'help' / 'quit'.
Examples:
  assess risks in the annual report   -> accounting
  legal risks in the contract         -> legal
  analyze the server outage           -> it
  code review                         -> developer
  general administrative tasks        -> general

Tip: paste log/contract text or a local file path into the request.
==================================================
"""},
    "ja": {"banner": """
==================================================
SHIELDAI - ローカル AI コントロールプレーン
==================================================
リクエストを入力、または 'help' / 'quit'。
例:
  決算書のリスク評価      -> accounting
  契約書の法律リスク      -> legal
  サーバー障害分析        -> it
  コードレビュー          -> developer
  一般事務処理            -> general

ヒント: ログや契約書テキスト、ローカルファイルパスをそのまま貼れます。
==================================================
"""},
}

# user-facing warnings - the 80/20 of CLI i18n: a JA user should not
# get a compromise warning in English. Technical field names and JSON
# keys stay English (they're protocol, not prose).
_CLI_STR["en"].update({
    "warn_chain": "[WARN] audit chain broken at #{at}: {reason} - "
                  "logs may have been tampered with",
    "abort_oneshot": "Aborting - refusing a one-shot run on a broken "
                     "audit chain.",
    "ack_prompt": "Continue anyway? The audit trail may be unreliable. "
                  "[y/N]: ",
    "abort_write": "Aborting - do not write to a broken audit chain.",
    "no_entries": "(no audit entries)",
    "warn_history": "WARNING: audit chain is broken - entries may be "
                    "tampered",
    "warn_forged": "WARNING: {n} forged work-record row(s) - "
                   "invalid signature",
    "no_tasks": "no tasks",
    "no_forged": "no forged work-record rows",
    "showing": "(showing {shown} of {total})",
    "goodbye": "Goodbye!",
    "lbl_agent": "Agent:", "lbl_model": "Model:",
    "lbl_complexity": "Complexity:",
    "lbl_plan": "Plan:",
    "lbl_unknowns": "Unknowns (verify locally, do not guess):",
    "lbl_first": "First principles: {n} assumptions questioned, "
                 "{m} fundamentals",
    "lbl_audit": "[audit_logs #{id}] request processed and logged",
    "no_answer": "(no answer)"})
_CLI_STR["ja"].update({
    "warn_chain": "[警告] #{at} で監査チェーンが破損: {reason} - "
                  "ログが改竄された可能性があります",
    "abort_oneshot": "中止します - 破損した監査チェーンでの "
                     "ワンショット実行を拒否しました。",
    "ack_prompt": "続行しますか? 監査証跡は信頼できない可能性が"
                  "あります。[y/N]: ",
    "abort_write": "中止します - 破損した監査チェーンには書き込み"
                   "ません。",
    "no_entries": "(監査エントリがありません)",
    "warn_history": "警告: 監査チェーンが破損 - エントリは改竄された"
                    "可能性があります",
    "warn_forged": "警告: {n} 件の偽造作業記録 - 署名が無効です",
    "no_tasks": "作業なし",
    "no_forged": "偽造作業記録行はありません",
    "showing": "({shown} / {total} 件を表示)",
    "goodbye": "終了します",
    "lbl_agent": "エージェント:", "lbl_model": "モデル:",
    "lbl_complexity": "複雑度:",
    "lbl_plan": "計画:",
    "lbl_unknowns": "不明点 (ローカルで検証・推測しない):",
    "lbl_first": "第一原理: {n} 個の仮定を疑問視・{m} 個の基礎要素",
    "lbl_audit": "[audit_logs #{id}] リクエストを処理して記録",
    "no_answer": "(回答なし)"})


def _t(lang: str, key: str, **fmt) -> str:
    """Localized string lookup with format args; falls back to en."""
    s = (_CLI_STR.get(lang, _CLI_STR["en"]).get(key)
         or _CLI_STR["en"].get(key, key))
    return s.format(**fmt) if fmt else s


def _lang_hint() -> str:
    """Display helpers run outside main()'s scope - re-detect the
    locale from env/argv/OS the same way main() did."""
    return _cli_lang(sys.argv[1:])


_CLI_STR["en"]["help"] = """Commands:
  <request>     classify -> plan -> execute (100% local) -> audit
  history [N]   show the N most recent audit entries (default 10)
  tasks         list the work record (task_queue + tasks, latest 20)
  status        show audit integrity and queue stats
  status --json machine-readable status (audit_integrity as JSON)
  verify --json machine-readable chain verify (ok/broken/forged as JSON)
  forged [--json] list forged work-record rows (invalid/unsigned signatures)
  history --json [N] machine-readable audit history (latest N as JSON)
  backup --json machine-readable backup path ({path} as JSON)
  decrypt --json FILE machine-readable decrypt+verify ({ok,entries_ok})
  export        write ALL audit entries + work record to an encrypted .enc file
  backup        snapshot the whole DB to backups/ (consistent VACUUM INTO)
  decrypt FILE  decrypt an .enc export with the local KMS key
  license [FILE] show license status / verify a license file
  version       show the product version
  update        check GitHub Releases for a newer version (the product's
                only outbound call - user-invoked, read-only)
  diag          paste-ready support info (version/OS/python/last crash)
  doctor        environment self-check - does my machine work?
                (crypto / data_dir / db / chain tip / ollama / license)
  report [--json] open a pre-filled GitHub issue with diag+crash (opt-in,
                never auto-sends) / emit the issue body as JSON
  verify        re-run the HMAC audit-chain check explicitly
  ui [ja|en]    open the local web dashboard in that locale
                (http://127.0.0.1:8765)
  config [lang <ja|en>] show/persist preferences (data_dir/config.json)
  help          show this message
  quit          exit
"""
_CLI_STR["ja"]["help"] = """コマンド:
  <リクエスト>  分類 -> 計画 -> 決定論的実行 (100% ローカル) -> 監査
  history [N]   直近 N 件の監査エントリを表示 (既定 10)
  tasks         作業記録を一覧 (task_queue + tasks・最新 20)
  status        監査の整合性とキュー統計を表示
  status --json 機械可読ステータス (audit_integrity の JSON)
  verify --json 機械可読チェーン検証 (ok/broken/forged の JSON)
  forged [--json] 偽造作業記録行を一覧 (無効/未署名シグネチャ)
  history --json [N] 機械可読監査履歴 (最新 N 件の JSON)
  backup --json 機械可読バックアップパス ({path} の JSON)
  decrypt --json FILE 機械可読復号+検証 ({ok,entries_ok})
  export        全監査エントリ+作業記録を暗号化 .enc に書き出す
  backup        DB 全体を backups/ にスナップショット (一貫 VACUUM INTO)
  decrypt FILE  ローカル KMS 鍵で .enc エクスポートを復号
  license [FILE] ライセンス状態表示 / ライセンスファイル検証
  version       製品バージョンを表示
  update        GitHub Releases の新版を確認 (製品唯一の外向き呼び出し・
                ユーザー起動・read-only)
  diag          サポート用診断情報 (version/OS/python/最終クラッシュ)
  doctor        環境自己診断 - 自分のマシンは動くか?
                (crypto / data_dir / db / chain tip / ollama / license)
  report [--json] プリフィル済み GitHub issue を開く (opt-in・自動送信なし)
                / issue 本文を JSON で出力
  verify        HMAC 監査チェーン検証を明示的に再実行
  ui [ja|en]    指定ロケールでローカル Web ダッシュボードを開く
                (http://127.0.0.1:8765)
  help          このメッセージを表示
  quit          終了
"""


def _cli_lang(argv) -> str:
    """SHIELDAI_LANG env -> '--lang xx' -> config.json -> OS locale."""
    lang = os.environ.get("SHIELDAI_LANG", "")
    if "--lang" in argv:
        i = argv.index("--lang")
        if i + 1 < len(argv):
            lang = argv[i + 1]
    if not lang:
        try:
            import json as _json
            from guardian_ai.paths import data_dir
            cfg = _json.loads(
                (data_dir() / "config.json").read_text("utf-8"))
            lang = cfg.get("lang", "")
        except Exception:
            lang = ""
    if not lang:
        import locale
        lang = (locale.getlocale()[0] or "")[:2]
    return lang if lang in _CLI_STR else "en"


def _write_config(**kv) -> None:
    """Persist user preferences to data_dir/config.json."""
    import json as _json
    from guardian_ai.paths import data_dir
    try:
        cfg = _json.loads(
            (data_dir() / "config.json").read_text("utf-8"))
    except Exception:
        cfg = {}
    cfg.update(kv)
    (data_dir() / "config.json").write_text(
        _json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


def _is_no_network() -> bool:
    """env var OR persisted config - either can air-gap the install."""
    if os.environ.get("SHIELDAI_NO_NETWORK"):
        return True
    try:
        import json as _json
        from guardian_ai.paths import data_dir
        cfg = _json.loads(
            (data_dir() / "config.json").read_text("utf-8"))
        return cfg.get("no_network") in ("on", "1", True)
    except Exception:
        return False


def show_history(conn, limit: int = 10) -> None:
    # show a snippet of the result too - a request without its outcome
    # is half an audit view (the user can't see what the agent did).
    rows = conn.execute(
        "SELECT id, agent, substr(request, 1, 50), timestamp, "
        "latency_ms, substr(result, 1, 50) "
        "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print(_t(_lang_hint(), "no_entries"))
        return
    # say when the view is capped - N rows are not the whole trail.
    total = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    if len(rows) < total:
        print(_t(_lang_hint(), "showing", shown=len(rows),
                 total=total))
    for row in reversed(rows):
        lat = f"  {row[4]}ms" if row[4] is not None else ""
        print(f"  #{row[0]} [{row[1]}] {row[3]}{lat}  {row[2]}")
        print(f"      -> {row[5]}")


def show_status(conn, executor) -> None:
    from guardian_ai import __version__
    audit = audit_integrity()
    print(f"version: {__version__}")
    agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    queued = conn.execute("SELECT status, COUNT(*) FROM task_queue GROUP BY status").fetchall()
    chain = audit.get("chain", {})
    chain_str = "ok" if chain.get("ok") else f"BROKEN at #{chain.get('broken_at')}" if chain else "n/a"
    print(f"audit_logs: {audit.get('audit_entries', '?')} entries, "
          f"integrity={audit.get('quick_check', audit.get('reason'))}, chain={chain_str}")
    print(f"agents: {agents}")
    print("task_queue:", ", ".join(f"{s}={n}" for s, n in queued) or "empty")
    # Observability means seeing WHAT was blocked/failed, not just how
    # many - surface the recent non-done tasks with their descriptions.
    notable = conn.execute(
        "SELECT q.agent, q.status, t.description FROM task_queue q "
        "JOIN tasks t ON q.task_id = t.id WHERE q.status != 'done' "
        "ORDER BY q.id DESC LIMIT 5").fetchall()
    for agent, st, desc in notable:
        print(f"  [{st}] {agent}: {desc or '(no description)'}")
    ollama = executor.llm
    if ollama.available():
        print(f"ollama: up, models={', '.join(ollama.models()) or 'none'}")
    else:
        print("ollama: down (deterministic mode)")


def show_result(result: dict, entry_id: int) -> None:
    thinking = result.get("thinking", {})
    execution = result.get("execution", {})
    lang = _lang_hint()
    print(f"\n{_t(lang, 'lbl_agent'):13s}{result['agent']}")
    print(f"{_t(lang, 'lbl_model'):13s}{result['model']}")
    print(f"{_t(lang, 'lbl_complexity'):13s}{result['complexity']}")
    print(_t(lang, "lbl_first",
             n=len(thinking.get("questioned", [])),
             m=len(thinking.get("unknowns", []))))
    print(_t(lang, "lbl_plan"))
    for step in result["tasks"]:
        print(f"  {step['id']}. [{step['type']}] {step['desc']}")
    if execution:
        print(f"\n{execution.get('answer', _t(lang, 'no_answer'))}")
    if thinking.get("unknowns"):
        print(_t(lang, "lbl_unknowns"))
        for u in thinking["unknowns"]:
            print(f"  - {u}")
    print(f"\n{_t(lang, 'lbl_audit', id=entry_id)}\n")


def main() -> None:
    router = Router()
    executor = Executor()
    conn = init_database()
    # 'shieldai <command>' runs one command and exits - the --json
    # surface is only scriptable when argv reaches it (piping the REPL
    # also works but is ugly). No argv -> interactive REPL as before.
    # Exception: a frozen exe with no args is the PRODUCT - a customer
    # double-clicking it expects the dashboard, not a REPL prompt.
    argv = sys.argv[1:]
    lang = _cli_lang(argv)
    # '--lang xx' is a global flag, not part of the command - strip the
    # pair so 'shieldai --lang ja status' runs 'status'.
    if "--lang" in argv:
        i = argv.index("--lang")
        argv = argv[:i] + argv[i + 2:]
    one_shot = " ".join(argv).strip()
    if not one_shot and getattr(sys, "frozen", False):
        one_shot = "ui"
    chain = verify_audit_chain(conn)
    if not chain.get("ok"):
        print(_t(lang, "warn_chain", at=chain.get("broken_at"),
                 reason=chain.get("reason", "")))
        if one_shot:
            # a non-interactive run cannot answer the ack gate - refuse
            # to touch a compromised trail (fail-closed, same as 'N').
            print(_t(lang, "abort_oneshot"), file=sys.stderr)
            conn.close()
            return
        try:
            choice = input(_t(lang, "ack_prompt")).strip().lower()
        except (KeyboardInterrupt, EOFError):
            choice = ""
        if choice not in ("y", "yes"):
            print(_t(lang, "abort_write"))
            conn.close()
            return

    if not one_shot:
        print(_CLI_STR[lang]["banner"])
    fed = iter([one_shot]) if one_shot else None
    try:
        while True:
            try:
                user_input = (next(fed) if fed is not None
                              else input("shieldai@> ")).strip()
            except (KeyboardInterrupt, EOFError, StopIteration):
                if not one_shot:
                    print()
                break

            if not user_input:
                continue
            cmd = user_input.lower()
            # conventional flags shouldn't be analyzed as requests -
            # '--version' / '--help' map to their commands, not the router.
            cmd = {"--version": "version", "-v": "version",
                   "--help": "help", "-h": "help",
                   "-V": "version"}.get(cmd, cmd)
            if cmd in ("quit", "exit", "q"):
                break
            if cmd == "help":
                print(_CLI_STR[lang]["help"])
                continue
            if cmd.startswith("history --json") or cmd.startswith("history "):
                # 'history --json [N]' gives the same entries in a
                # machine-readable form (consistent with status/verify
                # --json); the cap is configurable, not a fixed 50.
                if cmd.startswith("history --json"):
                    import json as _json
                    parts = cmd.split()
                    try:
                        lim = int(parts[2]) if len(parts) > 2 else 50
                    except ValueError:
                        lim = 50
                    rows = conn.execute(
                        "SELECT id, agent, request, result, timestamp, "
                        "latency_ms FROM audit_logs ORDER BY id DESC "
                        "LIMIT ?", (max(1, lim),)).fetchall()
                    # same warning as text history - the --json variant
                    # must not silently skip the broken-chain signal.
                    broken = not verify_audit_chain(conn).get("ok")
                    total = conn.execute(
                        "SELECT COUNT(*) FROM audit_logs").fetchone()[0]
                    print(_json.dumps(
                        {"chain_broken": broken,
                         "truncated": len(rows) < total,
                         "total": total,
                         "entries": [{"id": r[0], "agent": r[1],
                                      "request": r[2], "result": r[3],
                                      "timestamp": r[4],
                                      "latency_ms": r[5]}
                                     for r in rows]},
                        ensure_ascii=False))
                    continue
                try:
                    n = int(cmd.split()[1]) if cmd != "history" else 10
                except (IndexError, ValueError):
                    n = 10
                # same gate as export/backup - warn before showing a
                # compromised trail, don't silently present tampered data.
                if not verify_audit_chain(conn).get("ok"):
                    print(_t(lang, "warn_history"))
                show_history(conn, max(1, n))
                continue
            if cmd == "ui" or cmd.startswith("ui "):
                # 'ui en' / 'ui ja' opens the dashboard in that locale -
                # same ?lang= mechanism the header selector writes. A
                # persisted `config lang xx` supplies the default so the
                # CLI's language preference reaches the dashboard too.
                arg = (cmd.split()[1] if cmd.startswith("ui ") else "")
                if arg in ("ja", "en"):
                    ui_lang = arg
                else:
                    ui_lang = _lang_hint() if _lang_hint() in (
                        "ja", "en") else None
                from guardian_ai.webui import serve
                serve(lang=ui_lang)
                # blocks until Ctrl+C; returns here on exit
                continue
            if cmd == "tasks" or cmd == "tasks --json":
                # parity with the Web UI tasks tab - the work record is
                # not viewable from the CLI without this command.
                rows = conn.execute(
                    "SELECT q.status, q.agent, t.description, "
                    "q.created_at FROM task_queue q "
                    "JOIN tasks t ON q.task_id = t.id "
                    "ORDER BY q.id DESC LIMIT 20").fetchall()
                # same gate as history - warn before showing a forged
                # work record, don't silently present fabricated data.
                from guardian_ai.db import _forged_work_records
                forged = _forged_work_records(conn)
                if forged:
                    print(_t(lang, "warn_forged", n=forged))
                total = conn.execute(
                    "SELECT COUNT(*) FROM task_queue").fetchone()[0]
                if cmd.endswith("--json"):
                    import json as _json
                    from guardian_ai.db import _forged_work_records
                    forged = _forged_work_records(conn)
                    total = conn.execute(
                        "SELECT COUNT(*) FROM task_queue").fetchone()[0]
                    print(_json.dumps(
                        {"forged_tasks": forged,
                         "truncated": len(rows) < total,
                         "total": total,
                         "tasks": [{"status": r[0], "agent": r[1],
                                    "description": r[2],
                                    "created_at": r[3]}
                                   for r in rows]},
                        ensure_ascii=False))
                else:
                    if not rows:
                        print(_t(lang, "no_tasks"))
                    elif len(rows) < total:
                        # say when the view is capped - 20 rows are not
                        # the whole work record.
                        print(_t(_lang_hint(), "showing", shown=len(rows),
                 total=total))
                    for st, ag, desc, ts in rows:
                        print(f"[{st:8}] {ag:12} {(desc or '')[:50]} "
                              f"({ts[:16]})")
                continue
            if cmd == "status --json":
                # machine-readable status for monitoring/scripting.
                # /api/status carries version - the CLI parity should too.
                import json as _json
                from guardian_ai import __version__
                print(_json.dumps(
                    {**audit_integrity(), "version": __version__},
                    ensure_ascii=False))
                continue
            if cmd == "status":
                show_status(conn, executor)
                continue
            if cmd == "verify --json":
                # machine-readable verify - the integrity check is what
                # monitoring consumes, so it deserves the same --json as
                # status (consistent observability surface).
                import json as _json
                print(_json.dumps(verify_audit_chain(conn),
                                  ensure_ascii=False))
                continue
            if cmd == "forged" or cmd == "forged --json":
                # 'forged' lists WHICH work-record rows were fabricated -
                # 'verify: forged_tasks=N' alone can't identify them.
                from guardian_ai.db import _forged_rows
                rows = _forged_rows(conn)
                if cmd.endswith("--json"):
                    import json as _json
                    # same object shape as the other --json commands -
                    # a bare list is inconsistent with the surface.
                    print(_json.dumps(
                        {"count": len(rows), "forged_tasks": rows},
                        ensure_ascii=False))
                else:
                    if not rows:
                        print(_t(lang, "no_forged"))
                    for r in rows:
                        print(f"[{r['table']}] #{r['id']} {r['agent']} "
                              f"({r.get('reason','')})")
                continue
            if cmd == "version" or cmd == "version --json":
                from guardian_ai import __version__
                if cmd.endswith("--json"):
                    import json as _json
                    print(_json.dumps({"version": __version__}))
                else:
                    print(f"ShieldAI {__version__}")
                continue
            if cmd == "diag" or cmd == "diag --json":
                # paste-ready support info - 'please run diag' should be
                # enough to reproduce most field problems.
                import json as _json
                import platform
                from guardian_ai import __version__
                from guardian_ai.paths import data_dir
                crash = (data_dir() / "crash.log")
                info = {"version": __version__,
                        "os": f"{platform.system()} "
                              f"{platform.release()}",
                        "python": platform.python_version(),
                        "arch": platform.machine(),
                        "frozen": bool(getattr(sys, "frozen", False)),
                        "data_dir": str(data_dir()),
                        "last_crash": (crash.read_text(
                            encoding="utf-8")[-2000:]
                            if crash.exists() else None)}
                if cmd.endswith("--json"):
                    print(_json.dumps(info, ensure_ascii=False))
                else:
                    for k, v in info.items():
                        if k == "last_crash" and v:
                            print(f"last_crash:\n{v}")
                        elif k != "last_crash":
                            print(f"{k}: {v}")
                continue
            if cmd == "doctor" or cmd == "doctor --json":
                # environment self-check: 'diag' reports WHAT the env is,
                # 'doctor' tells the user WHETHER it works. The logic is
                # shared with the UI's /api/doctor endpoint.
                import json as _json
                from guardian_ai.compliance import doctor_checks
                checks = doctor_checks(conn, executor)
                if cmd.endswith("--json"):
                    print(_json.dumps(
                        {"checks": checks,
                         "all_ok": all(c["ok"] for c in checks)},
                        ensure_ascii=False))
                else:
                    for c in checks:
                        print(f"{'OK ' if c['ok'] else 'FAIL'} {c['name']}"
                              f"{(' - ' + c['detail']) if c['detail'] else ''}")
                continue
            if cmd == "report" or cmd == "report --json":
                # opt-in crash reporting for a local-only product: never
                # auto-send - gather diag, open a pre-filled GitHub issue
                # in the browser (or emit the body as JSON for headless),
                # the USER reviews and submits.
                # SHIELDAI_NO_NETWORK closes this too.
                import json as _json
                if _is_no_network():
                    print(_json.dumps({"error": "outbound calls disabled "
                                               "(no_network)"})
                          if cmd.endswith("--json")
                          else "outbound calls disabled (no_network)")
                    continue
                import platform
                import urllib.parse
                import webbrowser
                from guardian_ai import __version__
                from guardian_ai.paths import data_dir
                crash = data_dir() / "crash.log"
                crash_txt = (crash.read_text(
                    encoding="utf-8")[-1500:]
                    if crash.exists() else "(none)")
                body = (f"## diag\n"
                        f"- version: {__version__}\n"
                        f"- os: {platform.system()} "
                        f"{platform.release()}\n"
                        f"- python: {platform.python_version()}\n"
                        f"- arch: {platform.machine()}\n"
                        f"- frozen: {bool(getattr(sys,'frozen',False))}\n"
                        f"- data_dir: {data_dir()}\n\n"
                        f"## last crash\n```\n{crash_txt}\n```\n\n"
                        f"## what happened?\n")
                url = ("https://github.com/shizukutanaka/GuardianAI/"
                       f"issues/new?title=crash%3A+{__version__}&body="
                       + urllib.parse.quote(body))
                if cmd.endswith("--json"):
                    print(_json.dumps({"issue_body": body,
                                       "issue_url": url},
                                      ensure_ascii=False))
                else:
                    webbrowser.open(url)
                    print(f"opened a pre-filled issue - review and "
                          f"submit ({url[:70]}...)")
                continue
            if cmd.startswith("config"):
                # persist preferences so users don't repeat args each run:
                # 'config lang ja' writes data_dir/config.json; _cli_lang
                # picks it up after env/--lang, before OS locale.
                import json as _json
                parts = cmd.split()
                if len(parts) == 1 or parts[1] == "--json":
                    try:
                        from guardian_ai.paths import data_dir
                        cfg = _json.loads(
                            (data_dir() / "config.json")
                            .read_text("utf-8"))
                    except Exception:
                        cfg = {}
                    if cmd.endswith("--json"):
                        print(_json.dumps(cfg, ensure_ascii=False))
                    else:
                        print(_json.dumps(cfg, ensure_ascii=False,
                                          indent=2)
                              if cfg else "(no config set)")
                    continue
                if len(parts) == 3 and parts[1] in (
                        "lang", "no_network"):
                    _write_config(**{parts[1]: parts[2]})
                    print(f"saved {parts[1]}={parts[2]} to config.json")
                else:
                    print("usage: config lang <ja|en> | "
                          "config no_network <on|off>")
                continue
            if cmd == "update" or cmd == "update --json":
                # the product's ONLY outbound call: user-invoked, read-
                # only, sends nothing. Auto-update is deliberately NOT
                # built - without signature verification it would be a
                # downgrade/spoofing channel (fail-closed by design).
                # SHIELDAI_NO_NETWORK hard-cuts it for air-gapped sites.
                import json as _json
                if _is_no_network():
                    msg = "outbound calls disabled (no_network)"
                    print(_json.dumps({"error": msg})
                          if cmd.endswith("--json") else msg)
                    continue
                import json as _json
                import urllib.request
                from guardian_ai import __version__

                def _v(s):
                    s = str(s).lstrip("v").split("-")[0]
                    return tuple(int(x) for x in s.split(".")
                                 if x.isdigit())
                try:
                    req = urllib.request.Request(
                        "https://api.github.com/repos/shizukutanaka/"
                        "GuardianAI/releases/latest",
                        headers={"User-Agent": "shieldai-update-check",
                                 "Accept": "application/vnd.github+json"})
                    rel = _json.loads(
                        urllib.request.urlopen(req, timeout=10).read())  # nosec B310 - hardcoded https GitHub API URL
                    latest = str(rel.get("tag_name", "")).lstrip("v")
                    newer = (_v(latest) > _v(__version__)
                             or (_v(latest) == _v(__version__)
                                 and "-" in __version__
                                 and "-" not in latest))
                    out = {"current": __version__, "latest": latest,
                           "update_available": newer,
                           "url": rel.get("html_url")}
                except Exception as e:
                    # 404 = the repo has no releases yet - a normal
                    # state before the first tag, not a real failure.
                    msg = ("no releases published yet"
                           if "404" in str(e) else str(e))
                    out = {"current": __version__, "error": msg}
                if cmd.endswith("--json"):
                    print(_json.dumps(out, ensure_ascii=False))
                elif out.get("error"):
                    print(f"update check: {out['error']}")
                elif out["update_available"]:
                    print(f"new version: {out['latest']} "
                          f"(current {__version__})\n{out['url']}")
                else:
                    print(f"up to date ({__version__})")
                continue
            if cmd == "license" or cmd == "license --json" \
                    or cmd.startswith("license "):
                # offline Ed25519 license verification - consistent with
                # the local-only claim (no activation server, no telemetry).
                from guardian_ai.licensing import (verify_license,
                                                  license_status)
                json_out = "--json" in cmd
                files = [p for p in cmd.split()[1:]
                         if p != "--json"]
                st = (verify_license(files[0]) if files
                      else license_status())
                if json_out:
                    import json as _json
                    print(_json.dumps(st, ensure_ascii=False))
                elif st["valid"]:
                    exp = (f" expires {str(st['expires'])[:10]}"
                           if st.get("expires") else " perpetual")
                    print(f"licensed to {st['licensee']} - "
                          f"{st.get('seats')} seat(s){exp}")
                else:
                    # donation model: unlicensed is the normal free tier,
                    # not a fault - say so instead of implying a problem.
                    print(f"community edition ({st['reason']}) - "
                          "support: github.com/sponsors/shizukutanaka")
                continue
            if cmd == "verify":
                v = verify_audit_chain(conn)
                if v["ok"]:
                    print(f"chain ok: {v['entries']} entries verified "
                          "(HMAC chain + chain_state head/count)")
                else:
                    # broken_at is None for forged tasks / missing
                    # chain_state / trigger issues - '#None' is a wrong
                    # display, so show the reason alone there.
                    at = f" at #{v['broken_at']}" if v.get("broken_at") else ""
                    print(f"chain BROKEN{at}: {v.get('reason','')}")
                continue
            if cmd == "export --json":
                # machine-readable export path for automation - same
                # broken-chain signal as the text export, not skipped.
                import json as _json
                broken = not verify_audit_chain(conn).get("ok")
                try:
                    print(_json.dumps(
                        {"path": export_audit(conn),
                         "chain_broken": broken},
                        ensure_ascii=False))
                except RuntimeError as e:
                    print(_json.dumps({"error": str(e)}))
                continue
            if cmd == "export":
                # never silently snapshot a compromised trail - the same
                # gate as a request write: warn before exporting broken
                # data so the user knows the snapshot is suspect.
                if not verify_audit_chain(conn).get("ok"):
                    print("WARNING: audit chain is broken - this export "
                          "captures compromised data")
                try:
                    print(f"exported: {export_audit(conn)}")
                except RuntimeError as e:
                    print(f"export failed: {e}")
                continue
            if cmd == "backup" or cmd == "backup --json":
                # VACUUM INTO gives a consistent DB snapshot (unlike a
                # raw file copy, which can catch a mid-write page) - the
                # audit trail can be archived without weakening it.
                json_out = cmd.endswith("--json")
                # same gate as export - warn before archiving a
                # compromised trail, don't silently snapshot broken data.
                broken = not verify_audit_chain(conn).get("ok")
                if broken and not json_out:
                    print("WARNING: audit chain is broken - this backup "
                          "captures compromised data")
                try:
                    from guardian_ai.paths import data_dir
                    from datetime import datetime
                    dst = (data_dir() / "backups" /
                           f"audit-{datetime.now():%Y%m%d-%H%M%S}.db")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    conn.execute("VACUUM INTO ?", (str(dst),))
                    # keep only the latest 10 backups - an unbounded
                    # folder would repeat the audit-growth problem it
                    # was meant to solve.
                    snaps = sorted(dst.parent.glob("audit-*.db"))
                    for old in snaps[:-10]:
                        old.unlink()
                    if json_out:
                        import json as _json
                        print(_json.dumps({"path": str(dst),
                                           "chain_broken": broken},
                                          ensure_ascii=False))
                    else:
                        print(f"backup: {dst}")
                except Exception as e:
                    if json_out:
                        import json as _json
                        print(_json.dumps({"error": str(e)}))
                    else:
                        print(f"backup failed: {e}")
                continue
            if cmd.startswith("decrypt "):
                # 'decrypt --json FILE' returns the same verification as
                # JSON for automation (completes the --json surface).
                json_out = "--json" in user_input.split()
                files = [p for p in user_input.split()[1:]
                         if p != "--json"]
                if not files:
                    print("usage: decrypt [--json] FILE")
                    continue
                target = Path(files[-1].strip())
                try:
                    import json as _json
                    from guardian_ai.db import _state_hmac, _chain_hash
                    from guardian_ai.encryption import Encryption
                    raw = Encryption().decrypt(target.read_text(encoding="utf-8"))
                    try:
                        data = _json.loads(raw)
                        st = data.get("chain_state")
                        anchor_ok = bool(st and st.get("state_hmac")
                                         == _state_hmac(st.get("row_count"),
                                                        st.get("head")))
                        entries_ok = False
                        if anchor_ok:
                            prev = ""
                            for e in sorted(data["entries"],
                                            key=lambda x: x["id"]):
                                prev = _chain_hash(
                                    prev, e["agent"], e["request"],
                                    e["result"], e["timestamp"])
                            entries_ok = prev == st["head"]
                        if json_out:
                            print(_json.dumps(
                                {"ok": anchor_ok and entries_ok,
                                 "anchor_ok": anchor_ok,
                                 "entries_ok": entries_ok,
                                 "entries": len(data.get("entries", [])),
                                 "reason": None if entries_ok
                                          else "entries chain mismatch"
                                                if anchor_ok
                                                else "anchor signature invalid"},
                                ensure_ascii=False))
                            continue
                        if anchor_ok:
                            print(f"[anchor ok] signed chain_state "
                                  f"({st['row_count']} entries, head "
                                  f"{st['head'][:16]}...) - snapshot was "
                                  f"genuinely signed, not forged")
                            print("[entries ok] chain over exported "
                                  "entries reaches the signed head"
                                  if entries_ok else
                                  "[entries MISMATCH] exported entries "
                                  "do not form a chain ending at the "
                                  "signed head - incomplete snapshot")
                        elif st:
                            print("[anchor INVALID] chain_state signature "
                                  "mismatch - export may be tampered")
                        print(_json.dumps(data, ensure_ascii=False, indent=2))
                    except ValueError:
                        print(raw)
                except Exception as e:
                    print(_json.dumps({"error": str(e)}) if json_out
                          else f"decrypt failed: {e}")
                continue

            result = router.analyze(user_input)
            t0 = time.monotonic()
            result["execution"] = executor.execute(user_input, result)
            latency_ms = int((time.monotonic() - t0) * 1000)
            # audit first so tasks can link back to their audit entry -
            # a task with no audit entry is a forged work record.
            entry_id = audit_log(conn, result["agent"],
                                 redact(user_input), redact(str(result)),
                                 latency_ms=latency_ms)
            record_tasks(conn, result["agent"], result["complexity"],
                         result["tasks"], result["execution"].get("steps"),
                         audit_entry_id=entry_id)
            show_result(result, entry_id)
    finally:
        conn.close()

    if not one_shot:
        print(_t(lang, "goodbye"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # an unhandled crash must not drop a bare traceback on a
        # non-technical user - record it where support can find it.
        import traceback
        try:
            from guardian_ai.paths import data_dir
            crash = data_dir() / "crash.log"
            crash.write_text(traceback.format_exc(),
                             encoding="utf-8")
            print(f"\nShieldAI stopped unexpectedly - details were "
                  f"written to {crash}\nReport it with `diag` output.",
                  file=sys.stderr)
        except Exception:
            traceback.print_exc()
        sys.exit(1)
