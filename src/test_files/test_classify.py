import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test():
    from guardian_ai.router import Router
    r = Router()
    assert r.analyze('決算書のリスク評価')['agent'] == 'accounting'
    assert r.analyze('サーバー障害分析')['agent'] == 'it'
    assert r.analyze('コードレビュー')['agent'] == 'developer'


if __name__ == "__main__":
    test()
    print("PASS")
