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
    # general agent: fundamentals must not be duplicated
    out4 = fp.think('一般事務処理')
    assert len(out4['fundamentals']) == len(set(out4['fundamentals']))
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
    from guardian_ai.ollama_inference import OllamaClient
    router = Router()
    # dead port -> deterministic path, no LLM dependency in tests
    ex = Executor(llm=OllamaClient(host='http://127.0.0.1:9', timeout=1))

    # legal: contract-like text inline in the request
    req = "契約書の法律リスク: 甲は本件業務を遂行すること。乙は秘密を保持すること。第2版 2026年1月改訂"
    out = ex.execute(req, router.analyze(req))
    assert out['status'] == 'done', out.get('reason')
    assert any(e['kind'] == 'obligation' for e in out['evidence'])
    assert any(v['status'] == 'evidence_found' for v in out['verification'])
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
        out4 = Executor(llm=OllamaClient(host='http://127.0.0.1:9', timeout=1),
                        search_root=td).execute(req4, router.analyze(req4))
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
        names = c.models()
        assert isinstance(names, list) and names, 'daemon up but no models'
        assert c.pick_model('llama3.2:1b') is not None, 'live pick_model failed'
    else:
        assert c.models() == []
        assert c.pick_model('llama3:8b') is None
        # executor must still answer deterministically without a daemon
        from guardian_ai.router import Router
        from guardian_ai.executor import Executor
        out = Executor(llm=c).execute('一般事務処理', Router().analyze('一般事務処理'))
        assert out['status'] == 'done' and out['llm_model'] is None
""" + FOOTER,

    "chain": HEADER + """
def test():
    import os, tempfile
    from guardian_ai.db import init_database, audit_log, verify_audit_chain
    with tempfile.TemporaryDirectory() as td:
        conn = init_database(os.path.join(td, 't.db'))
        for i in range(3):
            audit_log(conn, 'general', f'req{i}', f'res{i}')
        assert verify_audit_chain(conn)['ok'] is True
        # append-only trigger blocks naive edits at the DB layer
        try:
            conn.execute("UPDATE audit_logs SET result='hacked' WHERE id=2")
            assert False, 'UPDATE must be blocked by append-only trigger'
        except Exception:
            conn.rollback()
        # attacker bypasses the trigger layer - the HMAC chain must catch it
        conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        conn.execute("UPDATE audit_logs SET result='hacked' WHERE id=2")
        conn.commit()
        v = verify_audit_chain(conn)
        assert v['ok'] is False and v['broken_at'] == 2
        # deleting the newest rows must also be caught by chain_state
        conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
        conn.execute("DELETE FROM audit_logs WHERE id=3")
        conn.commit()
        assert verify_audit_chain(conn)['ok'] is False
        conn.close()
""" + FOOTER,  # nosec B608 - template has literal SQL for trigger tests, no interpolation

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

    "main": HEADER + """
def test():
    # importing main.py must not explode - a syntax error in the CLI
    # entry point would break every command but the generated tests
    # (which import guardian_ai.*) would never notice.
    import importlib, main
    importlib.reload(main)
""" + FOOTER,

    "webui": HEADER + """
import json, tempfile, threading, urllib.request, os
def test():
    # env before imports so DB_PATH resolves to the temp dir
    td = tempfile.mkdtemp()
    os.environ['SHIELDAI_DATA_DIR'] = td
    from guardian_ai.webui import serve
    # start on an ephemeral port (port 0 -> OS assigns)
    from http.server import ThreadingHTTPServer
    import guardian_ai.webui as w
    srv = ThreadingHTTPServer(('127.0.0.1', 0), w._Handler)
    srv.router = __import__('guardian_ai.router', fromlist=['Router']).Router()
    srv.executor = __import__('guardian_ai.executor', fromlist=['Executor']).Executor()
    srv.token = 'test-tok'
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    base = f'http://127.0.0.1:{port}'
    def get(p, tok='test-tok'):
        req = urllib.request.Request(base + p, headers={'X-Token': tok})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())  # nosec B310 - localhost test server
    # the session token gates every /api/ endpoint - without it a local
    # process could read or pollute the audit trail
    try:
        get('/api/status', tok='')
        assert False, 'no-token request must 401'
    except urllib.error.HTTPError as e:
        assert e.code == 401
    try:
        get('/api/status', tok='wrong')
        assert False, 'wrong-token request must 401'
    except urllib.error.HTTPError as e:
        assert e.code == 401
    s = get('/api/status')
    assert 'audit_entries' in s and 'chain' in s
    assert get('/api/verify')['ok'] is True
    assert isinstance(get('/api/history?n=5'), list)
    assert isinstance(get('/api/tasks'), list)
    req = urllib.request.Request(base + '/api/request',
        data=json.dumps({'text':'server ERROR check'}).encode(),
        headers={'Content-Type':'application/json',
                 'X-Token':'test-tok'}, method='POST')
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())  # nosec B310 - localhost test server
    assert r['agent'] == 'it' and 'entry_id' in r
    srv.shutdown()
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
    # keep only the latest 20 reports - an unbounded folder would repeat
    # the same disk-fill problem as unbounded backups/exports.
    for old in sorted(REPORT_DIR.glob("report_*.json"))[:-20]:
        old.unlink()
    print(f"\n[OK] Report saved to {report_path}")


if __name__ == "__main__":
    main()
