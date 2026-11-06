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

BANNER = """
==================================================
SHIELDAI - LOCAL AI CONTROL PLANE
==================================================
Type a request, or 'help' / 'quit'.
Examples:
  決算書のリスク評価      -> accounting
  契約書の法律リスク      -> legal
  サーバー障害分析        -> it
  コードレビュー          -> developer
  一般事務処理            -> general

Tip: paste log/contract text or a local file path into the request.
==================================================
"""

HELP = """Commands:
  <request>     classify -> plan -> execute (100% local) -> audit
  history [N]   show the N most recent audit entries (default 10)
  status        show audit integrity and queue stats
  export        write the newest 100 audit entries to an encrypted .enc file
  decrypt FILE  decrypt an .enc export with the local KMS key
  verify        re-run the HMAC audit-chain check explicitly
  help          show this message
  quit          exit
"""


def show_history(conn, limit: int = 10) -> None:
    rows = conn.execute(
        "SELECT id, agent, substr(request, 1, 60), timestamp, latency_ms "
        "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print("(no audit entries)")
        return
    for row in reversed(rows):
        lat = f"  {row[4]}ms" if row[4] is not None else ""
        print(f"  #{row[0]} [{row[1]}] {row[3]}{lat}  {row[2]}")


def show_status(conn, executor) -> None:
    audit = audit_integrity()
    agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    queued = conn.execute("SELECT status, COUNT(*) FROM task_queue GROUP BY status").fetchall()
    chain = audit.get("chain", {})
    chain_str = "ok" if chain.get("ok") else f"BROKEN at #{chain.get('broken_at')}" if chain else "n/a"
    print(f"audit_logs: {audit.get('audit_entries', '?')} entries, "
          f"integrity={audit.get('quick_check', audit.get('reason'))}, chain={chain_str}")
    print(f"agents: {agents}")
    print("task_queue:", ", ".join(f"{s}={n}" for s, n in queued) or "empty")
    ollama = executor.llm
    if ollama.available():
        print(f"ollama: up, models={', '.join(ollama.models()) or 'none'}")
    else:
        print("ollama: down (deterministic mode)")


def show_result(result: dict, entry_id: int) -> None:
    thinking = result.get("thinking", {})
    execution = result.get("execution", {})
    print(f"\nAgent:      {result['agent']}")
    print(f"Model:      {result['model']}")
    print(f"Complexity: {result['complexity']}")
    print(f"First principles: {len(thinking.get('questioned', []))} assumptions questioned, "
          f"{len(thinking.get('unknowns', []))} unknowns to verify")
    print("Plan:")
    for step in result["tasks"]:
        print(f"  {step['id']}. [{step['type']}] {step['desc']}")
    if execution:
        print(f"\n{execution.get('answer', '(no answer)')}")
    if thinking.get("unknowns"):
        print("Unknowns (verify locally, do not guess):")
        for u in thinking["unknowns"]:
            print(f"  - {u}")
    print(f"\n[audit_logs #{entry_id}] request processed and logged\n")


def main() -> None:
    router = Router()
    executor = Executor()
    conn = init_database()
    chain = verify_audit_chain(conn)
    if not chain.get("ok"):
        print(f"[WARN] audit chain broken at #{chain.get('broken_at')}: "
              f"{chain.get('reason', '')} - logs may have been tampered with")
        # A control plane that claims integrity must not silently keep
        # writing to a compromised trail - require explicit user
        # acknowledgment rather than warn-and-continue (fail-open).
        try:
            choice = input("Continue anyway? The audit trail may be "
                           "unreliable. [y/N]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            choice = ""
        if choice not in ("y", "yes"):
            print("Aborting - do not write to a broken audit chain.")
            conn.close()
            return

    print(BANNER)
    try:
        while True:
            try:
                user_input = input("shieldai@> ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                break

            if not user_input:
                continue
            cmd = user_input.lower()
            if cmd in ("quit", "exit", "q"):
                break
            if cmd == "help":
                print(HELP)
                continue
            if cmd == "history" or cmd.startswith("history "):
                try:
                    n = int(cmd.split()[1]) if cmd != "history" else 10
                except (IndexError, ValueError):
                    n = 10
                show_history(conn, max(1, n))
                continue
            if cmd == "status":
                show_status(conn, executor)
                continue
            if cmd == "verify":
                v = verify_audit_chain(conn)
                if v["ok"]:
                    print(f"chain ok: {v['entries']} entries verified "
                          "(HMAC chain + chain_state head/count)")
                else:
                    print(f"chain BROKEN at #{v['broken_at']}: "
                          f"{v.get('reason','')}")
                continue
            if cmd == "export":
                try:
                    print(f"exported: {export_audit(conn)}")
                except RuntimeError as e:
                    print(f"export failed: {e}")
                continue
            if cmd.startswith("decrypt "):
                target = Path(user_input[8:].strip())
                try:
                    import json as _json
                    from guardian_ai.db import _state_hmac
                    from guardian_ai.encryption import Encryption
                    raw = Encryption().decrypt(target.read_text(encoding="utf-8"))
                    try:
                        data = _json.loads(raw)
                        # Verify the embedded signed anchor - without this
                        # check the chain_state in the export is decorative.
                        st = data.get("chain_state")
                        if st and st.get("state_hmac") == _state_hmac(
                                st.get("row_count"), st.get("head")):
                            print(f"[anchor ok] signed chain_state "
                                  f"({st['row_count']} entries, head "
                                  f"{st['head'][:16]}...) - snapshot was "
                                  f"genuinely signed, not forged")
                            # Prove the exported entries actually reach
                            # the signed head - a signed state beside a
                            # partial/inconsistent entry set is not a
                            # coherent audit snapshot.
                            from guardian_ai.db import _chain_hash
                            prev = ""
                            for e in sorted(data["entries"],
                                            key=lambda x: x["id"]):
                                prev = _chain_hash(
                                    prev, e["agent"], e["request"],
                                    e["result"], e["timestamp"])
                            if prev == st["head"]:
                                print("[entries ok] chain over exported "
                                      "entries reaches the signed head")
                            else:
                                print("[entries MISMATCH] exported entries "
                                      "do not form a chain ending at the "
                                      "signed head - incomplete snapshot")
                        elif st:
                            print("[anchor INVALID] chain_state signature "
                                  "mismatch - export may be tampered")
                        print(_json.dumps(data, ensure_ascii=False, indent=2))
                    except ValueError:
                        print(raw)
                except Exception as e:
                    print(f"decrypt failed: {e}")
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

    print("Goodbye!")


if __name__ == "__main__":
    main()
