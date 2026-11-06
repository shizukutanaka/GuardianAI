import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test():
    import os, tempfile
    from guardian_ai.db import init_database, audit_log, verify_audit_chain
    with tempfile.TemporaryDirectory() as td:
        conn = init_database(os.path.join(td, 't.db'))
        for i in range(3):
            audit_log(conn, 'general', f'req{i}', f'res{i}')
        assert verify_audit_chain(conn)['ok'] is True
        # silently rewrite a row - the chain must catch it
        conn.execute("UPDATE audit_logs SET result='hacked' WHERE id=2")
        conn.commit()
        v = verify_audit_chain(conn)
        assert v['ok'] is False and v['broken_at'] == 2
        conn.close()


if __name__ == "__main__":
    test()
    print("PASS")
