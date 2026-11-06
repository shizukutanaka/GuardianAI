import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

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


if __name__ == "__main__":
    test()
    print("PASS")
