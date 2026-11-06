import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

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


if __name__ == "__main__":
    test()
    print("PASS")
