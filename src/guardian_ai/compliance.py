"""ShieldAI Compliance - verifiable local checks only.

A compliance module that always answers "compliant" is a false oracle.
This implementation reports only what can actually be verified on this
platform:

  - sensitive_data : scan text for key/PII-shaped patterns (reported, not blocked)
  - audit_integrity : sqlite quick_check + audit_logs row count on the local DB
  - locality       : confirm no network egress is performed by this module
                     (structural guarantee - there is no network code here)
"""
import os
import re
import sqlite3
from typing import Any, Dict, List

from guardian_ai.db import DB_PATH as _DB_PATH
from guardian_ai.db import verify_audit_chain

# Patterns that suggest secrets or regulated identifiers in free text.
_SENSITIVE_PATTERNS = [
    ("private_key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # short keys like sk-ABC123456789 (12 chars) were missed at >=16
    ("api_key", re.compile(r"\b(sk|pk|key|api)[-_][A-Za-z0-9]{10,}\b", re.I)),
    ("service_token", re.compile(
        r"\b(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{10,}|"
        r"xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{20,})\b")),
    ("bearer_token", re.compile(r"bearer\s+[A-Za-z0-9._-]{10,}", re.I)),
    ("password", re.compile(
        r"(?:password|passwd|pwd|secret|パスワード|密码|비밀번호)\s*[:=：]\s*[^\s,;。]{4,}", re.I)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # JP My Number (12 digits) - distinct from phone (10-11) and CC (13-19)
    ("my_number_jp", re.compile(r"(?<!\d)\d{12}(?!\d)")),
]


def scan_sensitive(text: str) -> List[str]:
    """Return the names of sensitive-data patterns found in text."""
    findings = []
    for name, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text or ""):
            findings.append(name)
    return findings


def redact(text: str) -> str:
    """Replace sensitive-pattern spans with <REDACTED:name>.

    For an audit trail, deleting the secret beats encrypting it: there is
    no key to manage and nothing left to leak.
    """
    out = text or ""
    for name, pattern in _SENSITIVE_PATTERNS:
        out = pattern.sub(f"<REDACTED:{name}>", out)
    return out


def audit_integrity(db_path: str = _DB_PATH) -> Dict[str, Any]:
    """Verify the local audit database is intact and untampered.

    Two independent layers: sqlite structure (quick_check) and the
    content hash chain (verify_audit_chain) - the latter catches a
    manually edited row, which structural checks cannot.
    """
    if not os.path.exists(db_path):
        return {"ok": False, "reason": "database file not found"}
    try:
        conn = sqlite3.connect(db_path)
        try:
            quick = conn.execute("PRAGMA quick_check").fetchone()[0]
            count = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
            chain = verify_audit_chain(conn)
        finally:
            conn.close()
    except sqlite3.Error as e:
        return {"ok": False, "reason": str(e)}
    return {
        "ok": quick == "ok" and chain["ok"],
        "quick_check": quick,
        "audit_entries": count,
        "chain": chain,
    }


def check_compliance(data: Any = None) -> Dict[str, Any]:
    """Run all verifiable checks. `data` may be a string or a dict with
    'request'/'result' text to scan for sensitive content."""
    text = ""
    if isinstance(data, str):
        text = data
    elif isinstance(data, dict):
        text = " ".join(str(data.get(k, "")) for k in ("request", "result", "agent"))

    findings = scan_sensitive(text)
    audit = audit_integrity()

    checks = {
        "sensitive_data": {"status": "clean" if not findings else "found",
                           "findings": findings},
        "audit_integrity": audit,
        "locality": {"status": "pass",
                     "note": "no network egress exists in this codebase path"},
    }

    # Sensitive-pattern hits are reported as warnings, not hard failures;
    # a broken audit trail is a hard failure.
    if not audit.get("ok"):
        status = "fail"
    elif findings:
        status = "warn"
    else:
        status = "pass"

    return {"status": status, "checks": checks}


__all__ = ["check_compliance", "scan_sensitive", "audit_integrity", "redact"]
