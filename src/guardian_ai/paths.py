"""GuardianAI data-directory resolution.

Runtime state (SQLite DB, KMS keys) is user state, not source code:
- normal source tree -> stays next to guardian_ai/ (existing behaviour)
- frozen (PyInstaller) EXE -> %LOCALAPPDATA%/GuardianAI - __file__ inside
  a frozen build points at a temp extraction dir that is wiped between
  runs, so data there would silently vanish on restart
- inside a zipapp (or any non-writable location) -> ~/.guardianai/
- GUARDIANAI_DATA_DIR env var overrides everything

The product was once called ShieldAI. Installs from that era keep
working: SHIELDAI_* env vars are read when the GUARDIANAI_* one is
unset, and an existing ShieldAI data dir is used in place (never
moved) when no GuardianAI one exists - moving it would orphan the
DPAPI-bound keys and the audit chain.
"""
import os
import sys
from pathlib import Path

LEGACY_NAME = "ShieldAI"


def env(name: str, default: str = "") -> str:
    """GUARDIANAI_<name>, falling back to the legacy SHIELDAI_<name>."""
    return (os.environ.get(f"GUARDIANAI_{name}")
            or os.environ.get(f"SHIELDAI_{name}")
            or default)


def _prefer_existing(current: Path, legacy: Path) -> Path:
    return legacy if legacy.is_dir() and not current.exists() else current


def data_dir() -> Path:
    override = env("DATA_DIR")
    if override:
        d = Path(override)
    elif getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        d = _prefer_existing(base / "GuardianAI", base / LEGACY_NAME)
    else:
        here = Path(__file__).resolve().parent
        if here.is_dir():           # normal source tree
            d = here
        else:                       # inside a zipapp: __file__ is not a real dir
            d = _prefer_existing(Path.home() / ".guardianai",
                                 Path.home() / ".shieldai")
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = ["data_dir", "env"]
