import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

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


if __name__ == "__main__":
    test()
    print("PASS")
