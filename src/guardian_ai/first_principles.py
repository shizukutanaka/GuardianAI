"""First-Principles thinking engine (Elon Musk method).

Conventional thinking (thinking by analogy) inherits hidden assumptions.
This module separates every request into 4 deterministic steps:

  1. strip        - Surface and doubt the solutions assumed by the request
  2. fundamentals - Break down until only facts verifiable on this platform remain
  3. unknowns     - Name the information that is still unclear (turn it into a
                    verification task, never let a model fabricate it)
  4. reconstruct  - Rebuild the shortest task chain from the fundamentals alone

No LLM required. Deterministic, 100% local, safe even offline.
An LLM is only an enhancement that fills in the results of the task chain.
"""
from typing import Any, Dict, List

# ------------------------------------------------------------------
# 1-2: fundamentals per agent (verifiable truth on this platform)
# ------------------------------------------------------------------
FUNDAMENTALS: Dict[str, List[str]] = {
    "accounting": [
        "Accounting period boundaries are the truth (figures are meaningful only when the period is clear)",
        "Double-entry bookkeeping (a figure is accepted only when found on both sides of expense and revenue)",
        "Arithmetic is machine-verifiable (a model's figure output is always recomputed locally)",
    ],
    "legal": [
        "What is not written in the contract document is not an obligation (that which is not written does not become effective)",
        "An obligation must be traceable back to the responsible party and its basis rule",
        "Risk is a judgement, not a fact (a judgement exists only once the tolerance threshold is defined)",
    ],
    "hr": [
        "Any skill claim requires a verifiable record of date, business, and evidence (self-report is not proof)",
        "Claimed business and company are independent facts (connecting the two by inference is an assumption)",
    ],
    "it": [
        "Failure sequence (the first timestamp is the starting point of the root cause)",
        "Correlation between machines requires clock synchronization and verification",
        "An untestable hypothesis is not a diagnosis (reproduction conditions must be testable)",
    ],
    "developer": [
        "The reproduction steps are the only ground truth (an explanation without reproduction is unverified)",
        "A test is the oracle for correctness (code not run against an oracle is not proven correct)",
        "The scope of a change is determined by imports and the build system (guessing that nothing else is affected is an assumption)",
    ],
    "medical": [
        "Diagnosis = observable measurements (clinical text not cross-checked with measurements is inference)",
        "Treatment must satisfy regulations (regulations take priority over the model's judgement)",
        "PHI anonymization must be verified in advance, irreversibly, one-way",
    ],
    "general": [
        "The goal = the goal the request itself states (not the presupposed or approximate goal behind it)",
        "Processing is 100% local (data leaving the platform is physically impossible, so verification is also local-only)",
        "The model's context, memory, and time window are fixed physical limits (verifiable constraints)",
    ],
}

# Surface "default solutions" to doubt, per agent
QUESTIONED: Dict[str, List[Dict[str, str]]] = {
    "legal": [
        {"assumption": "pass the full text of the contract document to the model in one go",
         "challenge": "the local LLM's context window is the hard physical limit (llama3:8b is bound by VRAM)",
         "principle": "rank by importance and put only the necessary paragraphs in the window"},
        {"assumption": "trust the model's output of obligations as-is",
         "challenge": "the model generates 'seemingly plausible' text; it is not one that reads the document",
         "principle": "each obligation must be verifiable down to a paragraph of the original"},
    ],
    "accounting": [
        {"assumption": "have the model do the addition and subtraction of figures as-is",
         "challenge": "arithmetic is verifiable, so having the model do it leaves no one to doubt it",
         "principle": "leave the arithmetic to the machine; have the model only do the classification"},
    ],
    "it": [
        {"assumption": "dump the whole log onto the model, then take the conclusion",
         "challenge": "the full log exceeds the context, so the model 'reads' only a fragment",
         "principle": "locally narrow the range by time, level, and module before entering the model"},
    ],
    "developer": [
        {"assumption": "the model reads, writes, and generates code directly",
         "challenge": "there is no guarantee that generated code passes the tests; passing is the definition",
         "principle": "the task chain must end with local execution and test verification"},
    ],
    "hr": [
        {"assumption": "judge that the person 'is suitable' directly from the resume",
         "challenge": "what is written on a resume is self-reported; it is not a verified fact",
         "principle": "each claim must be checked back against a timeline, business record, and evidence"},
    ],
    "medical": [
        {"assumption": "after extraction, process the clinical text on an external service",
         "challenge": "this platform is 100% local; sending PHI outside is physically forbidden",
         "principle": "first verify the PHI anonymization, then process only locally"},
    ],
    "general": [
        {"assumption": "solve it in one shot with the same task chain",
         "challenge": "a large, unsegmented task wastes the model's limited context and gets diluted",
         "principle": "only tasks broken down to the smallest verifiable unit"},
    ],
}

# Additional assumptions to doubt, depending on request content.
# Each entry: (keywords, {assumption, challenge, principle}).
# Keywords match case-insensitively; Japanese and English both supported.
REQUEST_TRIGGERS = [
    (("risk", "リスク"), {
        "assumption": "leave the threshold of 'risk' up to the model's judgement",
        "challenge": "the tolerance threshold is defined by the party (the model cannot know the other side)",
        "principle": "explicitly define the tolerance threshold first, then judge against it"}),
    (("plan", "計画", "プラン"), {
        "assumption": "the schedule and budget are left as an afterthought",
        "challenge": "any plan without a boundary is meaningless; the boundary is a constraint, not a preference",
        "principle": "lock the schedule and budget boundary before generating the plan"}),
    (("contract", "契約書"), {
        "assumption": "treat 'the latest version' as the valid document",
        "challenge": "the revision that is valid must be verified from the header, signature, and date",
        "principle": "first pin down the valid version, then analyse"}),
]

# Unknowns (turned into verification tasks, never filled in by the model)
# Each entry: (keywords, description). Keywords match case-insensitively.
UNKNOWN_RULES = [
    (("risk", "リスク"), "Definition of the risk tolerance threshold (what counts as high risk)"),
    (("plan", "計画", "プラン"), "Time span and budget ceiling (the boundaries of the plan)"),
    (("server", "サーバー", "障害"), "Reproduction condition (whether the failure can be made to reproduce)"),
    (("code", "コード"), "Correctness oracle (what counts as passing via tests/execution)"),
    (("contract", "契約書"), "The revision of the valid contract document"),
    # Agent-specific unknowns so medical/hr/accounting requests get a
    # verifiable check instead of the generic "Definition of done" fallback.
    (("症状", "処方", "カルテ", "medical", "診断", "病历", "诊断", "处方",
      "환자", "진단", "처방", "patient", "diagnosis", "prescription",
      "symptom"), "Dosage and unit basis (whether amounts are in mg/ml/etc)"),
    (("履歴書", "スキル", "採用", "経験", "简历", "面试", "招聘",
      "이력서", "채용", "면접", "resume", "interview", "hiring",
      "candidate"), "Evidence for claimed experience (whether it is backed by a record)"),
    (("決算", "仕訳", "会計", "勘定", "决算", "会计", "报销",
      "결산", "회계", "account", "ledger", "invoice",
      "expense"), "Applicable accounting standard and closing period"),
]


def _matches(request_lower: str, keywords) -> bool:
    return any(kw in request_lower for kw in keywords)


class FirstPrinciples:
    """First-principles thinking engine: deterministic and LLM-independent."""

    def think(self, request: str, agent: Any = "general", complexity: str = "medium") -> Dict[str, Any]:
        """Run the full 4-step method and return the thought path + the task chain."""
        agent_name = getattr(agent, "value", str(agent))
        req_lower = request.lower()

        questioned = list(QUESTIONED.get(agent_name, QUESTIONED["general"]))
        for keywords, item in REQUEST_TRIGGERS:
            if _matches(req_lower, keywords) and item not in questioned:
                questioned.append(dict(item))

        fundamentals = list(FUNDAMENTALS.get(agent_name, FUNDAMENTALS["general"]))
        if agent_name != "general":
            fundamentals += FUNDAMENTALS["general"]  # shared physical laws

        unknowns = []
        for keywords, item in UNKNOWN_RULES:
            if _matches(req_lower, keywords):
                unknowns.append(item)
        if not unknowns:
            unknowns = ["Definition of done (what counts as the completion criterion)"]

        plan = self.reconstruct(request, agent_name, unknowns, complexity)

        return {
            "agent": agent_name,
            "questioned": questioned,    # 1. strip assumptions
            "facts": [
                "The request itself states the goal; local 100% processing is a hard constraint",
                "The model's context, memory, and time window are verifiable physical boundaries",
            ],
            "fundamentals": fundamentals,  # 2. break down to fundamentals
            "unknowns": unknowns,          # 3. name the unknowns
            "plan": plan,                  # 4. reconstruct from fundamentals
        }

    def reconstruct(self, request: str, agent_name: str, unknowns: List[str],
                    complexity: str = "medium") -> List[Dict]:
        """Build the shortest task chain starting only from the fundamentals."""
        steps: List[Dict] = [
            {"type": "ingestion", "desc": "Bring in the source materials as only local files (do not send anything outside the platform)"},
            {"type": "extraction", "desc": "Break down to fundamentals: keep only what can be verified (separate what is written, found, or measured from inference)"},
        ]
        if unknowns:
            steps.append({"type": "verification", "desc": "Verify the unknowns locally against the source data (do not let the model fabricate them)"})
        if complexity == "complex":
            steps.append({"type": "delegation", "desc": "Verification sub-tasks are independent, so run them in parallel"})
        steps.append({"type": "synthesis", "desc": "Reconstruct from fundamentals only: derive the shortest answer (every judgement must trace back to a fundamental)"})
        steps.append({"type": "audit", "desc": "Log the entire thought path (questioned assumptions / fundamentals / verified unknowns) to audit_logs"})

        return [{"id": i, "type": t["type"], "desc": t["desc"], "from_fundamental": True}
                for i, t in enumerate(steps, start=1)]


__all__ = ["FirstPrinciples"]
