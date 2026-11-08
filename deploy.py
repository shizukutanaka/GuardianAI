#!/usr/bin/env python3
"""ShieldAI deployment script.

  --test    run the full test suite (gate for --deploy)
  --deploy  build dist/shieldai.pyz - a single-file zipapp of src/.
            Local-first: no PyPI, no twine, no cloud. Run it with
            `python dist/shieldai.pyz`.
"""
import subprocess
import sys
import zipapp
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
SRC = ROOT / "src"
DIST = ROOT / "dist"


def run_tests() -> bool:
    result = subprocess.run([sys.executable, str(SRC / "test_auto.py")])
    return result.returncode == 0


def _zipapp_filter(path: Path) -> bool:
    parts = set(path.parts)
    if parts & {"__pycache__", ".shield_keys", "test_files", "test_reports"}:
        return False
    return not path.name.endswith(
        (".db", ".db-journal", ".pyc", ".pyo", ".key", ".enc"))


def build() -> bool:
    DIST.mkdir(exist_ok=True)
    import shutil
    sys.path.insert(0, str(SRC))
    from guardian_ai import __version__
    # versioned artifact (like the exe/installer naming) + a
    # shieldai.pyz copy so `python dist/shieldai.pyz` still works.
    target = DIST / f"shieldai-{__version__}.pyz"
    zipapp.create_archive(SRC, target=str(target), main="main:main",
                          filter=_zipapp_filter, compressed=True)
    simple = DIST / "shieldai.pyz"
    shutil.copy2(target, simple)
    print(f"[OK] built {target} ({target.stat().st_size} bytes)")
    print(f"     run: {sys.executable} {simple}")
    return True


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        ok = run_tests()
        print("[OK] Pre-deployment tests passed" if ok else "[FAIL] Pre-deployment tests failed")
        sys.exit(0 if ok else 1)
    if len(sys.argv) > 1 and sys.argv[1] == "--deploy":
        if not run_tests():
            print("[FAIL] tests failed - refusing to deploy")
            sys.exit(1)
        build()
        return
    print(__doc__)


if __name__ == "__main__":
    main()
