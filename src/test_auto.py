#!/usr/bin/env python3
"""ShieldAI Automation Tests - generates and runs real, executable tests.

Each generated file calls test() under __main__, so a PASS means the
assertions actually ran. sys.path is fixed inside every generated file,
so tests pass regardless of the caller's working directory.
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent          # src/
ROOT_DIR = SRC_DIR.parent                          # repo root
TEST_DIR = SRC_DIR / "test_files"
REPORT_DIR = SRC_DIR / "test_reports"

CONFIG = {
    "retry_count": 3,
    "timeout": 300,
}

HEADER = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))\n"
)

FOOTER = '\n\nif __name__ == "__main__":\n    test()\n    print("PASS")\n'

TESTS = {
    "classify": HEADER + """
def test():
    from guardian_ai.router import Router
    r = Router()
    assert r.analyze('決算書のリスク評価')['agent'] == 'accounting'
    assert r.analyze('サーバー障害分析')['agent'] == 'it'
    assert r.analyze('コードレビュー')['agent'] == 'developer'
""" + FOOTER,

    "agents": HEADER + """
def test():
    from guardian_ai.router import Router
    r = Router()
    result = r.analyze('契約書の法律リスク')
    for key in ('agent', 'model', 'complexity', 'tasks', 'thinking'):
        assert key in result, key
    assert result['agent'] == 'legal'
    assert len(result['tasks']) > 0
""" + FOOTER,

    "think": HEADER + """
def test():
    from guardian_ai.first_principles import FirstPrinciples
    fp = FirstPrinciples()
    out = fp.think('契約書の法律リスク', agent='legal')
    assert out['agent'] == 'legal'
    assert len(out['fundamentals']) > 0
    assert len(out['plan']) >= 4
    # Japanese keyword triggers must fire
    out2 = fp.think('サーバー障害分析')
    assert any('Reproduction' in u for u in out2['unknowns'])
    out3 = fp.think('契約書レビュー')
    assert any('valid version' in q['principle'] for q in out3['questioned'])
""" + FOOTER,

    "encrypt": HEADER + """
def test():
    from guardian_ai.encryption import Encryption
    e = Encryption()
    ct = e.encrypt('test')
    assert e.decrypt(ct) == 'test'
    # Key persistence: a fresh instance must decrypt old ciphertext
    e2 = Encryption()
    assert e2.decrypt(ct) == 'test'
""" + FOOTER,

    "tamper": HEADER + """
def test():
    from guardian_ai.encryption import Encryption
    e = Encryption()
    ct = e.encrypt('integrity check')
    raw = bytearray(__import__('base64').b64decode(ct))
    raw[-1] ^= 0xFF  # flip a tag bit
    import base64
    bad = base64.b64encode(bytes(raw)).decode()
    try:
        e.decrypt(bad)
    except ValueError:
        return
    raise AssertionError('tampered ciphertext was accepted')
""" + FOOTER,

    "search": HEADER + """
def test():
    import os
    from guardian_ai.local_search import LocalSearch
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    s = LocalSearch(src)
    py_files = s.search_files('*.py')
    assert len(py_files) > 0
    assert all(f.endswith('.py') for f in py_files)
    # excluded dirs must not be walked
    assert not any('venv' in f.split(os.sep) for f in py_files)
""" + FOOTER,

    "execute": HEADER + """
def test():
    from guardian_ai.router import Router
    from guardian_ai.executor import Executor
    router, ex = Router(), Executor()

    # legal: contract-like text inline in the request
    req = "契約書の法律リスク: 甲は本件業務を遂行すること。乙は秘密を保持すること。第2版 2026年1月改訂"
    out = ex.execute(req, router.analyze(req))
    assert out['status'] == 'done', out.get('reason')
    assert any(e['kind'] == 'obligation' for e in out['evidence'])
    assert any(v['status'] == 'verified' for v in out['verification'])
    assert 'ローカル解析結果' in out['answer']

    # it: pasted log line
    req2 = "サーバー障害分析 ERROR 2026-11-07T01:23:45 connection timeout host 10.0.0.1"
    out2 = ex.execute(req2, router.analyze(req2))
    assert out2['status'] == 'done'
    assert any(e['kind'] in ('error', 'timestamp', 'host') for e in out2['evidence'])

    # medical: PHI-shaped content must block before extraction
    req3 = "カルテ確認 -----BEGIN RSA PRIVATE KEY----- test"
    out3 = ex.execute(req3, router.analyze(req3))
    assert out3['status'] == 'blocked'

    # ingestion: bare filename resolved under search_root via LocalSearch
    import os, tempfile
    with tempfile.TemporaryDirectory() as td:
        fp = os.path.join(td, 'server_log.txt')
        with open(fp, 'w', encoding='utf-8') as f:
            f.write('ERROR 2026-11-07T01:00:00 disk full on db01')
        req4 = "サーバー障害分析 server_log.txt"
        out4 = Executor(search_root=td).execute(req4, router.analyze(req4))
        assert out4['status'] == 'done'
        assert len(out4['files']) == 1
        assert any(e['kind'] == 'error' for e in out4['evidence'])
""" + FOOTER,

    "ollama": HEADER + """
def test():
    import time
    from guardian_ai.ollama_inference import OllamaClient
    c = OllamaClient(timeout=1.0)
    t0 = time.time()
    avail = c.available()
    assert time.time() - t0 < 5, 'available() must fail fast'
    if avail:
        assert isinstance(c.models(), list)
    else:
        assert c.models() == []
        assert c.pick_model('llama3:8b') is None
        # executor must still answer deterministically without a daemon
        from guardian_ai.router import Router
        from guardian_ai.executor import Executor
        out = Executor(llm=c).execute('一般事務処理', Router().analyze('一般事務処理'))
        assert out['status'] == 'done' and out['llm_model'] is None
""" + FOOTER,

    "export": HEADER + """
def test():
    import os, tempfile
    from guardian_ai.db import init_database, audit_log, export_audit
    from guardian_ai.encryption import Encryption
    with tempfile.TemporaryDirectory() as td:
        conn = init_database(os.path.join(td, 't.db'))
        audit_log(conn, 'general', 'secret request 42', 'some result')
        path = export_audit(conn, out_dir=td)
        raw = open(path, encoding='utf-8').read()
        assert 'secret request 42' not in raw   # ciphertext on disk
        dec = Encryption().decrypt(raw)
        assert 'secret request 42' in dec       # decrypts back
        conn.close()
""" + FOOTER,

    "compliance": HEADER + """
def test():
    from guardian_ai.compliance import check_compliance, audit_integrity
    from guardian_ai.db import init_database
    init_database()
    assert audit_integrity()['ok'] is True
    out = check_compliance({'request': 'normal business request'})
    assert out['status'] in ('pass', 'warn')
    warn = check_compliance({'request': 'token sk-' + 'A' * 20})
    assert warn['checks']['sensitive_data']['status'] == 'found'
    assert warn['status'] == 'warn'
""" + FOOTER,
}


def run_test_file(test_file: Path):
    """Run one generated test file; retry up to retry_count times."""
    for _ in range(CONFIG["retry_count"]):
        try:
            result = subprocess.run(
                [sys.executable, str(test_file)],
                capture_output=True, text=True,
                timeout=CONFIG["timeout"], cwd=str(ROOT_DIR))
            if result.returncode == 0:
                return "PASS", result.stdout.strip()
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            continue
    return "FAIL", ""


def run_tests():
    TEST_DIR.mkdir(exist_ok=True)
    results = []
    for i, (name, source) in enumerate(TESTS.items()):
        test_file = TEST_DIR / f"test_{name}.py"
        test_file.write_text(source, encoding="utf-8")

        status, output = run_test_file(test_file)
        results.append({"file": test_file.name, "status": status})
        marker = "PASS" if status == "PASS" else "FAIL"
        print(f"[{i+1}/{len(TESTS)}] {test_file.name}: {marker}")
        if status == "FAIL":
            # rerun once to surface the error for debugging
            r = subprocess.run([sys.executable, str(test_file)],
                               capture_output=True, text=True,
                               timeout=CONFIG["timeout"], cwd=str(ROOT_DIR))
            print(r.stderr.strip() or r.stdout.strip())
    return results


def main():
    results = run_tests()
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")

    print("\n" + "=" * 50)
    print(f"Total: {total}, Passed: {passed}, Failed: {total - passed}")
    print(f"Success rate: {(passed / total * 100):.1f}%")
    print("=" * 50)

    REPORT_DIR.mkdir(exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(),
        "passed": passed,
        "failed": total - passed,
        "results": results,
    }
    report_path = REPORT_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[OK] Report saved to {report_path}")


if __name__ == "__main__":
    main()
