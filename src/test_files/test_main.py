import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test():
    # importing main.py must not explode - a syntax error in the CLI
    # entry point would break every command but the generated tests
    # (which import guardian_ai.*) would never notice.
    import importlib, main
    importlib.reload(main)


if __name__ == "__main__":
    test()
    print("PASS")
