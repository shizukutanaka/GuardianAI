#!/usr/bin/env python3
"""GuardianAI Automation Tests - generates and runs real, executable tests.

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

    "export_collision": HEADER + """
def test():
    import json, os, tempfile
    from guardian_ai.db import init_database, audit_log, export_audit
    from guardian_ai.encryption import Encryption
    with tempfile.TemporaryDirectory() as td:
        conn = init_database(os.path.join(td, 't.db'))
        audit_log(conn, 'general', 'collision first', 'result one')
        first = export_audit(conn, out_dir=td)
        audit_log(conn, 'general', 'collision second', 'result two')
        second = export_audit(conn, out_dir=td)
        assert first != second
        assert os.path.exists(first)
        assert os.path.exists(second)

        enc = Encryption()
        def load(path):
            raw = open(path, encoding='utf-8').read()
            return json.loads(enc.decrypt(raw))
        first_payload = load(first)
        second_payload = load(second)
        first_requests = [e['request'] for e in first_payload['entries']]
        second_requests = [e['request'] for e in second_payload['entries']]
        assert first_requests == ['collision first']
        assert second_requests == ['collision second', 'collision first']
        conn.close()
""" + FOOTER,

    "backup_collision": HEADER + """
def test():
    import os, sqlite3, tempfile
    from guardian_ai.db import init_database, audit_log, backup_database
    with tempfile.TemporaryDirectory() as td:
        conn = init_database(os.path.join(td, 't.db'))
        audit_log(conn, 'general', 'backup collision first', 'result one')
        first = backup_database(conn, out_dir=td)
        audit_log(conn, 'general', 'backup collision second', 'result two')
        second = backup_database(conn, out_dir=td)
        assert first != second
        assert os.path.exists(first)
        assert os.path.exists(second)

        def requests(path):
            snap = sqlite3.connect(path)
            try:
                return [r[0] for r in snap.execute(
                    'SELECT request FROM audit_logs ORDER BY id')]
            finally:
                snap.close()
        assert requests(first) == ['backup collision first']
        assert requests(second) == ['backup collision first',
                                    'backup collision second']
        conn.close()
""" + FOOTER,

    "backup_perm": HEADER + """
def test():
    import os, tempfile
    from guardian_ai.db import init_database, audit_log, backup_database
    with tempfile.TemporaryDirectory() as td:
        conn = init_database(os.path.join(td, 't.db'))
        audit_log(conn, 'general', 'backup permission check', 'result')
        path = backup_database(conn, out_dir=td)
        assert os.path.exists(path)
        if os.name != 'nt':
            mode = os.stat(path).st_mode & 0o777
            assert mode == 0o600, oct(mode)
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

    "config": HEADER + """
def test():
    # env before importing main - config resolution must use this
    # isolated data dir, never the developer's real one.
    import importlib, json, tempfile
    td = tempfile.mkdtemp()
    os.environ['GUARDIANAI_DATA_DIR'] = td
    import main
    importlib.reload(main)

    corrupt = b'{not json'
    cfg_path = os.path.join(td, 'config.json')
    backup_path = os.path.join(td, 'config.json.backup')
    with open(cfg_path, 'wb') as f:
        f.write(corrupt)
    main._write_config(lang='ja')
    assert os.path.exists(backup_path)
    with open(backup_path, 'rb') as f:
        assert f.read() == corrupt
    with open(cfg_path, encoding='utf-8') as f:
        cfg = json.load(f)
    assert cfg['lang'] == 'ja'

    # A valid config is merged in place - no backup means no spurious
    # evidence-loss artifact when nothing was corrupt.
    td2 = tempfile.mkdtemp()
    os.environ['GUARDIANAI_DATA_DIR'] = td2
    cfg_path2 = os.path.join(td2, 'config.json')
    backup_path2 = os.path.join(td2, 'config.json.backup')
    with open(cfg_path2, 'w', encoding='utf-8') as f:
        f.write('{"no_network": "on"}')
    main._write_config(lang='en')
    with open(cfg_path2, encoding='utf-8') as f:
        cfg2 = json.load(f)
    assert cfg2['no_network'] == 'on'
    assert cfg2['lang'] == 'en'
    assert not os.path.exists(backup_path2)
""" + FOOTER,

    "kms": HEADER + """
def test():
    import tempfile
    from pathlib import Path
    names = ('GUARDIANAI_KEY_AUDIT_CHAIN', 'SHIELDAI_KEY_AUDIT_CHAIN',
             'GUARDIANAI_KEY', 'SHIELDAI_KEY', 'GUARDIANAI_DATA_DIR')
    saved = {k: os.environ.pop(k, None) for k in names}
    try:
        from guardian_ai import kms

        with tempfile.TemporaryDirectory() as td:
            os.environ['GUARDIANAI_DATA_DIR'] = td
            key_dir = Path(td) / '.shield_keys'
            key_dir.mkdir()
            key_path = key_dir / 'audit_chain.key'
            backup_path = key_dir / 'audit_chain.key.backup'
            corrupt = b'corrupt key material'
            key_path.write_bytes(corrupt)
            key = kms.get_key('audit_chain')
            assert len(key) == 32
            assert backup_path.read_bytes() == corrupt
            blob = key_path.read_bytes()
            if os.name == 'nt':
                assert kms._dpapi(blob, protect=False) == key
            else:
                assert len(blob) == 32
                assert blob == key
            assert kms.get_key('audit_chain') == key

        with tempfile.TemporaryDirectory() as td:
            os.environ['GUARDIANAI_DATA_DIR'] = td
            key_dir = Path(td) / '.shield_keys'
            key_path = key_dir / 'audit_chain.key'
            backup_path = key_dir / 'audit_chain.key.backup'
            valid = b'V' * 32
            if os.name == 'nt':
                kms._write_key_file(key_path, valid)
            else:
                key_dir.mkdir()
                key_path.write_bytes(valid)
            assert kms.get_key('audit_chain') == valid
            assert not backup_path.exists()
    finally:
        os.environ.pop('GUARDIANAI_DATA_DIR', None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
""" + FOOTER,

    "webui_error_log": HEADER + """
def test():
    import tempfile
    from pathlib import Path
    saved = os.environ.get('GUARDIANAI_DATA_DIR')
    try:
        with tempfile.TemporaryDirectory() as td:
            os.environ['GUARDIANAI_DATA_DIR'] = td
            from guardian_ai.webui import _log_error
            log = Path(td) / 'webui-errors.log'
            log.write_bytes(b'old entry' + bytes([10, 0xff, 0xfe, 10]))
            _log_error('first new error')
            text = log.read_text(encoding='utf-8')
            assert 'first new error' in text
            _log_error('second new error')
            text = log.read_text(encoding='utf-8')
            assert 'first new error' in text
            assert 'second new error' in text
    finally:
        if saved is None:
            os.environ.pop('GUARDIANAI_DATA_DIR', None)
        else:
            os.environ['GUARDIANAI_DATA_DIR'] = saved
""" + FOOTER,

    "crash_log": HEADER + """
def test():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        crash = Path(td) / 'crash.log'
        crash.write_bytes(b'original failure' + bytes([10, 0xff, 0xfe, 10])
                          + b'final traceback line' + bytes([10]))
        diag_text = crash.read_text(encoding='utf-8', errors='replace')[-2000:]
        report_text = crash.read_text(encoding='utf-8', errors='replace')[-1500:]
        for text in (diag_text, report_text):
            assert chr(0xfffd) in text
            assert text.rstrip().endswith('final traceback line')
    main_py = Path(__file__).resolve().parents[1] / 'main.py'
    src = main_py.read_text(encoding='utf-8')
    assert 'encoding="utf-8", errors="replace")[-2000:]' in src
    assert 'encoding="utf-8", errors="replace")[-1500:]' in src
""" + FOOTER,

    "crash_backup": HEADER + """
def test():
    import tempfile
    from pathlib import Path
    import main as cli_main
    with tempfile.TemporaryDirectory() as td:
        crash = Path(td) / 'crash.log'
        backup = crash.with_name(crash.name + '.backup')

        assert cli_main._preserve_previous_crash(crash) is False
        assert not backup.exists()

        crash.write_bytes(b'')
        assert cli_main._preserve_previous_crash(crash) is False
        assert not backup.exists()

        original = (b'first traceback' + bytes([10, 0, 0xff, 0xfe, 10])
                    + b'final line' + bytes([10]))
        crash.write_bytes(original)
        assert cli_main._preserve_previous_crash(crash) is True
        assert backup.read_bytes() == original
        assert crash.read_bytes() == original

        second = b'second traceback\\n'
        crash.write_bytes(second)
        assert cli_main._preserve_previous_crash(crash) is True
        assert backup.read_bytes() == second
""" + FOOTER,

    "webui": HEADER + """
import json, tempfile, threading, urllib.request, os
def test():
    # env before imports so DB_PATH resolves to the temp dir
    td = tempfile.mkdtemp()
    os.environ['GUARDIANAI_DATA_DIR'] = td
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

    "ui_url_perm": HEADER + """
def test():
    import stat, tempfile
    from pathlib import Path
    from guardian_ai.webui import _write_ui_url
    with tempfile.TemporaryDirectory() as td:
        url_file = Path(td) / 'ui_url.txt'
        url_file.write_text('stale', encoding='utf-8')
        if os.name != 'nt':
            os.chmod(url_file, 0o644)
        url = 'http://127.0.0.1:8765/?t=test-token&lang=ja'
        _write_ui_url(url_file, url)
        assert url_file.read_text(encoding='utf-8') == url
        if os.name != 'nt':
            assert stat.S_IMODE(url_file.stat().st_mode) == 0o600
""" + FOOTER,

    "naming": HEADER + """
import os, sys, tempfile
from pathlib import Path
def test():
    from guardian_ai import paths, licensing
    saved = {k: os.environ.pop(k, None) for k in (
        'GUARDIANAI_DATA_DIR', 'SHIELDAI_DATA_DIR', 'LOCALAPPDATA')}
    try:
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        # pre-rename installs: the legacy env var alone still works
        os.environ['SHIELDAI_DATA_DIR'] = a
        assert paths.data_dir() == Path(a)
        # the new name wins when both are set
        os.environ['GUARDIANAI_DATA_DIR'] = b
        assert paths.data_dir() == Path(b)
        del os.environ['GUARDIANAI_DATA_DIR'], os.environ['SHIELDAI_DATA_DIR']
        # frozen exe: an existing ShieldAI dir is used in place (moving
        # it would orphan the keys); a fresh machine gets GuardianAI
        base = Path(tempfile.mkdtemp())
        os.environ['LOCALAPPDATA'] = str(base)
        sys.frozen = True
        try:
            assert paths.data_dir() == base / 'GuardianAI'
            base2 = Path(tempfile.mkdtemp())
            (base2 / 'ShieldAI').mkdir()
            os.environ['LOCALAPPDATA'] = str(base2)
            assert paths.data_dir() == base2 / 'ShieldAI'
        finally:
            del sys.frozen
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    # licenses signed as ShieldAI stay valid; other products don't
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import base64, json
    priv = Ed25519PrivateKey.generate()
    old = licensing.PUBLIC_KEY_B64
    licensing.PUBLIC_KEY_B64 = base64.b64encode(priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    try:
        def lic(product):
            body = {'product': product, 'licensee': 't', 'seats': 1,
                    'expires': None, 'features': []}
            f = Path(tempfile.mkdtemp()) / 'x.license'
            f.write_text(json.dumps({'license': body, 'signature':
                base64.b64encode(priv.sign(licensing._canonical(body))).decode()}))
            return licensing.verify_license(f)['valid']
        assert lic('GuardianAI') and lic('ShieldAI') and not lic('Other')
    finally:
        licensing.PUBLIC_KEY_B64 = old
    # one name on the user-facing surface: no new ShieldAI strings in the
    # CLI, the dashboard or the README beyond the documented compat note
    root = Path(__file__).resolve().parents[2]
    for rel in ('src/main.py', 'src/guardian_ai/webui.py', 'README.md'):
        compat = False
        for n, line in enumerate((root / rel).read_text('utf-8').splitlines(), 1):
            if line.startswith('## '):
                compat = line == '## Renamed from ShieldAI'
            low = line.lower().replace('img.shields.io', '').replace('shield_ai.db', '')
            assert 'shield' not in low or compat, (rel, n, line)
""" + FOOTER,

    "mcp": HEADER + """
def test():
    # Real stdio round-trip: spawn the MCP server as a subprocess and
    # speak newline-delimited JSON-RPC to it, exactly as a client does.
    import json, os, subprocess, sys
    src = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..'))
    env = dict(os.environ, PYTHONPATH=src)
    proc = subprocess.Popen(
        [sys.executable, '-m', 'guardian_ai.mcp_server'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, encoding='utf-8', env=env)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "classify_request",
                    "arguments": {"request": "契約書の法律リスク"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "scan_sensitive",
                    "arguments": {"text": "key is AKIAIOSFODNN7EXAMPLE ok"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "redact_text",
                    "arguments": {"text": "password: hunter2 please"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "audit_integrity", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 7, "method": "no/such"},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "execute_request",
                    "arguments": {"request": "x"}}},
    ]
    payload = "\\n".join(json.dumps(r) for r in requests) + "\\n"
    out, _ = proc.communicate(payload, timeout=60)
    assert proc.returncode == 0, proc.returncode
    by_id = {}
    for line in out.splitlines():
        msg = json.loads(line)
        by_id[msg["id"]] = msg
    # initialize handshake
    init = by_id[1]["result"]
    assert init["serverInfo"]["name"] == "guardian-ai"
    assert init["protocolVersion"] == "2024-11-05"
    assert "tools" in init["capabilities"]
    # tool list: exactly the read-only set, nothing executable
    names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert names == {"classify_request", "scan_sensitive", "redact_text",
                     "audit_integrity", "list_agents"}, names
    # classify: pure analysis routes to the legal agent
    body = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert by_id[3]["result"]["isError"] is False
    assert body["agent"] == "legal"
    assert len(body["tasks"]) > 0
    # scan: pattern names only - the secret itself must not come back
    body = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert "aws_access_key" in body["findings"]
    assert "AKIAIOSFODNN7EXAMPLE" not in by_id[4]["result"]["content"][0]["text"]
    # redact: the secret is replaced, not echoed
    body = json.loads(by_id[5]["result"]["content"][0]["text"])
    assert "<REDACTED:password>" in body["redacted"]
    assert "hunter2" not in body["redacted"]
    # audit_integrity: shape only (ok depends on whether a DB exists)
    body = json.loads(by_id[6]["result"]["content"][0]["text"])
    assert "ok" in body
    # unknown method is a protocol error; unknown tool is a tool error
    assert by_id[7]["error"]["code"] == -32601
    assert by_id[8]["result"]["isError"] is True
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
