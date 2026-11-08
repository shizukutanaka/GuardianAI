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
  report        open a pre-filled GitHub issue with diag+crash (opt-in,
                never auto-sends)
  verify        re-run the HMAC audit-chain check explicitly
  ui            open the local web dashboard (http://127.0.0.1:8765)
  help          show this message
  quit          exit
"""


def show_history(conn, limit: int = 10) -> None:
    # show a snippet of the result too - a request without its outcome
    # is half an audit view (the user can't see what the agent did).
    rows = conn.execute(
        "SELECT id, agent, substr(request, 1, 50), timestamp, "
        "latency_ms, substr(result, 1, 50) "
        "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print("(no audit entries)")
        return
    # say when the view is capped - N rows are not the whole trail.
    total = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    if len(rows) < total:
        print(f"(showing {len(rows)} of {total})")
    for row in reversed(rows):
        lat = f"  {row[4]}ms" if row[4] is not None else ""
        print(f"  #{row[0]} [{row[1]}] {row[3]}{lat}  {row[2]}")
        print(f"      -> {row[5]}")


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
    # 'shieldai <command>' runs one command and exits - the --json
    # surface is only scriptable when argv reaches it (piping the REPL
    # also works but is ugly). No argv -> interactive REPL as before.
    # Exception: a frozen exe with no args is the PRODUCT - a customer
    # double-clicking it expects the dashboard, not a REPL prompt.
    one_shot = " ".join(sys.argv[1:]).strip()
    if not one_shot and getattr(sys, "frozen", False):
        one_shot = "ui"
    chain = verify_audit_chain(conn)
    if not chain.get("ok"):
        print(f"[WARN] audit chain broken at #{chain.get('broken_at')}: "
              f"{chain.get('reason', '')} - logs may have been tampered with")
        if one_shot:
            # a non-interactive run cannot answer the ack gate - refuse
            # to touch a compromised trail (fail-closed, same as 'N').
            print("Aborting - refusing a one-shot run on a broken "
                  "audit chain.", file=sys.stderr)
            conn.close()
            return
        try:
            choice = input("Continue anyway? The audit trail may be "
                           "unreliable. [y/N]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            choice = ""
        if choice not in ("y", "yes"):
            print("Aborting - do not write to a broken audit chain.")
            conn.close()
            return

    if not one_shot:
        print(BANNER)
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
                    print("WARNING: audit chain is broken - entries may "
                          "be tampered")
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
                # same gate as history - warn before showing a forged
                # work record, don't silently present fabricated data.
                from guardian_ai.db import _forged_work_records
                forged = _forged_work_records(conn)
                if forged:
                    print(f"WARNING: {forged} forged work-record row(s) - "
                          "invalid signature")
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
                        print("no tasks")
                    elif len(rows) < total:
                        # say when the view is capped - 20 rows are not
                        # the whole work record.
                        print(f"(showing {len(rows)} of {total})")
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
                        print("no forged work-record rows")
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
            if cmd == "report":
                # opt-in crash reporting for a local-only product: never
                # auto-send - gather diag, open a pre-filled GitHub issue
                # in the browser, the USER reviews and submits.
                import json as _json
                import platform
                import urllib.parse
                import webbrowser
                from guardian_ai import __version__
                from guardian_ai.paths import data_dir
                crash = data_dir() / "crash.log"
                body = (f"## diag\n"
                        f"- version: {__version__}\n"
                        f"- os: {platform.system()} "
                        f"{platform.release()}\n"
                        f"- python: {platform.python_version()}\n"
                        f"- arch: {platform.machine()}\n"
                        f"- frozen: {bool(getattr(sys,'frozen',False))}\n"
                        f"- data_dir: {data_dir()}\n\n"
                        f"## last crash\n```\n"
                        f"{(crash.read_text(encoding='utf-8')[-1500:]"
                        f" if crash.exists() else '(none)')}\n```\n\n"
                        f"## what happened?\n")
                url = ("https://github.com/shizukutanaka/GuardianAI/"
                       f"issues/new?title=crash%3A+{__version__}&body="
                       + urllib.parse.quote(body))
                webbrowser.open(url)
                print(f"opened a pre-filled issue - review and submit "
                      f"({url[:70]}...)")
                continue
            if cmd == "update" or cmd == "update --json":
                # the product's ONLY outbound call: user-invoked, read-
                # only, sends nothing. Auto-update is deliberately NOT
                # built - without signature verification it would be a
                # downgrade/spoofing channel (fail-closed by design).
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
                        urllib.request.urlopen(req, timeout=10).read())
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
        print("Goodbye!")


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
