import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test():
    import os
    from guardian_ai.local_search import LocalSearch
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    s = LocalSearch(src)
    py_files = s.search_files('*.py')
    assert len(py_files) > 0
    assert all(f.endswith('.py') for f in py_files)
    # excluded dirs must not be walked
    assert not any('venv' in f.split(os.sep) for f in py_files)


if __name__ == "__main__":
    test()
    print("PASS")
