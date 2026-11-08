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


if __name__ == "__main__":
    test()
    print("PASS")
