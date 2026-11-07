"""ShieldAI data-directory resolution.

Runtime state (SQLite DB, KMS keys) is user state, not source code:
- normal source tree -> stays next to guardian_ai/ (existing behaviour)
- frozen (PyInstaller) EXE -> %LOCALAPPDATA%/ShieldAI - __file__ inside
  a frozen build points at a temp extraction dir that is wiped between
  runs, so data there would silently vanish on restart
- inside a zipapp (or any non-writable location) -> ~/.shieldai/
- SHIELDAI_DATA_DIR env var overrides everything
"""
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("SHIELDAI_DATA_DIR")
    if env:
        d = Path(env)
    elif getattr(sys, "frozen", False):
        d = Path(os.environ.get("LOCALAPPDATA",
                                str(Path.home()))) / "ShieldAI"
    else:
        here = Path(__file__).resolve().parent
        if here.is_dir():           # normal source tree
            d = here
        else:                       # inside a zipapp: __file__ is not a real dir
            d = Path.home() / ".shieldai"
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = ["data_dir"]
