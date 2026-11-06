import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test():
    from guardian_ai.encryption import Encryption
    e = Encryption()
    ct = e.encrypt('integrity check')
    raw = bytearray(__import__('base64').b64decode(ct))
    raw[-1] ^= 0xFF  # flip a tag bit
    import base64
    bad = base64.b64encode(bytes(raw)).decode()
    try:
        e.decrypt(bad)
    except ValueError:
        return
    raise AssertionError('tampered ciphertext was accepted')


if __name__ == "__main__":
    test()
    print("PASS")
