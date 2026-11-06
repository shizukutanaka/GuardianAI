import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

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


if __name__ == "__main__":
    test()
    print("PASS")
