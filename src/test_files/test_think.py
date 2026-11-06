import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

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


if __name__ == "__main__":
    test()
    print("PASS")
