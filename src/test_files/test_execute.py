import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

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


if __name__ == "__main__":
    test()
    print("PASS")
