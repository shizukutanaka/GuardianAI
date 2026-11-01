#!/usr/bin/env python3
"""ShieldAI Automation Tests Generator"""
import argparse
import sys
import subprocess
import time
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / "src"))

CONFIG = {
    "retry_count": 3,
    "timeout": 300,
    "output_dir": Path(__file__).parent / "test_reports",
}

TESTS = {
    "classify": "def test_classify_python(): from guardian_ai.router import Router; r = Router(); assert r.analyze('Generate Python report')['agent'].startswith('GENERAL')",
    "encrypt": "def test_encrypt(): from guardian_ai.encryption import Encryption; e = Encryption(); assert e.decrypt(e.encrypt('Hello')) == 'Hello'",
    "search": "def test_search_python(): from guardian_ai.local_search import LocalSearch; s = LocalSearch('.'); assert len(s.search_files('*.py')) > 0",
    "agents": "def test_agents_list(): from guardian_ai.router import Router; r = Router(); assert 'agent' in r.analyze('test').keys()",
}

def run_tests():
    passed, failed, results = 0, 0, []
    for i, name in enumerate(TESTS.keys()):
        test_file = Path(__file__).parent / "test_files" / f"test_{name}.py"
        test_file.parent.mkdir(exist_ok=True)
        test_file.write_text(TESTS[name])
        
        for attempt in range(CONFIG["retry_count"]):
            try:
                result = subprocess.run([sys.executable, test_file], capture_output=True, text=True, timeout=CONFIG["timeout"])
                if result.returncode == 0:
                    passed += 1
                    results.append({"file": test_file.name, "status": "PASS"})
                    print(f"[{i+1}/{len(TESTS)}] {test_file.name}: PASS")
                    break
                else:
                    failed += 1
                    results.append({"file": test_file.name, "status": "FAIL"})
            except:
                failed += 1
                results.append({"file": test_file.name, "status": "FAIL"})
    return results

def main():
    results = run_tests()
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    
    print("\n" + "="*50)
    print(f"Total: {total}, Passed: {passed}, Failed: {total-passed}")
    print(f"Success rate: {(passed/total*100):.1f}%")
    print("="*50)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "passed": passed,
        "failed": total - passed,
        "results": results,
    }
    (Path(__file__).parent / "test_reports").mkdir(exist_ok=True)
    (Path(__file__).parent / "test_reports" / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(report, indent=2))
    print(f"\n✓ Report saved to test_reports/")

if __name__ == "__main__":
    main()
