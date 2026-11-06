import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test():
    from guardian_ai.encryption import Encryption
    e = Encryption()
    ct = e.encrypt('test')
    assert e.decrypt(ct) == 'test'
    # Key persistence: a fresh instance must decrypt old ciphertext
    e2 = Encryption()
    assert e2.decrypt(ct) == 'test'


if __name__ == "__main__":
    test()
    print("PASS")
