#!/usr/bin/env python3
"""Build the standalone shieldai.exe - no Python required on the
customer's machine (PyInstaller --onefile).

  python scripts/build_exe.py

Output: dist/shieldai.exe. The exe is unsigned - v1 ships it with
SHA256SUMS.txt for manual verification (code signing comes later;
unsigned+broken is safer than unsigned+silent).
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
SRC = ROOT / "src"
DIST = ROOT / "dist"


def main() -> int:
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    for stale in ROOT.glob("shieldai.spec"):
        stale.unlink()
    rc = subprocess.call([
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--clean", "--name", "shieldai",
        "--paths", str(SRC),
        "--collect-all", "guardian_ai",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build"),
        str(SRC / "main.py"),
    ], cwd=str(ROOT))
    if rc:
        return rc
    # PyInstaller emits shieldai.exe on Windows, bare 'shieldai'
    # elsewhere - the release matrix builds on all three.
    exe = DIST / ("shieldai.exe" if sys.platform == "win32"
                  else "shieldai")
    # publish the hash - an unsigned binary is verifiable if the digest
    # is delivered through a second channel (the GitHub release).
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {exe.name}\n", encoding="utf-8")
    print(f"[OK] {exe} ({exe.stat().st_size} bytes)")
    print(f"[OK] {sums}: {digest}")
    # built != works - run 'version' on the artifact as the final gate
    # so a corrupt exe doesn't get an OK (same self-check as deploy.py).
    try:
        r = subprocess.run([str(exe), "version"],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f"[FAIL] exe self-check could not run: {e}")
        return 1
    if r.returncode != 0 or "ShieldAI" not in r.stdout:
        print(f"[FAIL] exe self-check: rc={r.returncode} "
              f"{r.stderr[:200]}")
        return 1
    print(f"[OK] exe self-check: {r.stdout.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
