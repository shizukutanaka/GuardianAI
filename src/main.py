"""ShieldAI CLI - classify requests, execute first-principles plans, audit everything."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guardian_ai.db import init_database, audit_log, record_tasks
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
  <request>   classify -> plan -> execute (100% local) -> audit
  help        show this message
  quit        exit
"""


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

            result = router.analyze(user_input)
            result["execution"] = executor.execute(user_input, result)
            record_tasks(conn, result["agent"], result["complexity"], result["tasks"])
            entry_id = audit_log(conn, result["agent"], user_input, str(result))
            show_result(result, entry_id)
    finally:
        conn.close()

    print("Goodbye!")


if __name__ == "__main__":
    main()
