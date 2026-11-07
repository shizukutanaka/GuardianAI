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
  tasks         list the work record (task_queue + tasks, latest 20)
  status        show audit integrity and queue stats
  status --json machine-readable status (audit_integrity as JSON)
  verify --json machine-readable chain verify (ok/broken/forged as JSON)
  history --json [N] machine-readable audit history (latest N as JSON)
  backup --json machine-readable backup path ({path} as JSON)
  decrypt --json FILE machine-readable decrypt+verify ({ok,entries_ok})
  export        write ALL audit entries + work record to an encrypted .enc file
  backup        snapshot the whole DB to backups/ (consistent VACUUM INTO)
  decrypt FILE  decrypt an .enc export with the local KMS key
  verify        re-run the HMAC audit-chain check explicitly
  ui            open the local web dashboard (http://127.0.0.1:8765)
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
                    print(_json.dumps(
                        [{"id": r[0], "agent": r[1], "request": r[2],
                          "result": r[3], "timestamp": r[4],
                          "latency_ms": r[5]} for r in rows],
                        ensure_ascii=False))
                    continue
                try:
                    n = int(cmd.split()[1]) if cmd != "history" else 10
                except (IndexError, ValueError):
                    n = 10
                show_history(conn, max(1, n))
                continue
            if cmd == "ui":
                from guardian_ai.webui import serve
                serve()  # blocks until Ctrl+C; returns here on exit
                continue
            if cmd == "tasks" or cmd == "tasks --json":
                # parity with the Web UI tasks tab - the work record is
                # not viewable from the CLI without this command.
                rows = conn.execute(
                    "SELECT q.status, q.agent, t.description, "
                    "q.created_at FROM task_queue q "
                    "JOIN tasks t ON q.task_id = t.id "
                    "ORDER BY q.id DESC LIMIT 20").fetchall()
                if cmd.endswith("--json"):
                    import json as _json
                    print(_json.dumps(
                        [{"status": r[0], "agent": r[1],
                          "description": r[2], "created_at": r[3]}
                         for r in rows], ensure_ascii=False))
                else:
                    if not rows:
                        print("no tasks")
                    for st, ag, desc, ts in rows:
                        print(f"[{st:8}] {ag:12} {(desc or '')[:50]} "
                              f"({ts[:16]})")
                continue
            if cmd == "status --json":
                # machine-readable status for monitoring/scripting.
                import json as _json
                print(_json.dumps(audit_integrity(), ensure_ascii=False))
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
                # machine-readable export path for automation.
                import json as _json
                try:
                    print(_json.dumps(
                        {"path": export_audit(conn)},
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

    print("Goodbye!")


if __name__ == "__main__":
    main()
