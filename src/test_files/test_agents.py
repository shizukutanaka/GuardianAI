import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test():
    from guardian_ai.router import Router
    r = Router()
    result = r.analyze('契約書の法律リスク')
    for key in ('agent', 'model', 'complexity', 'tasks', 'thinking'):
        assert key in result, key
    assert result['agent'] == 'legal'
    assert len(result['tasks']) > 0


if __name__ == "__main__":
    test()
    print("PASS")
