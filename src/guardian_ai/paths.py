"""ShieldAI data-directory resolution.

Runtime state (SQLite DB, KMS keys) is user state, not source code:
- normal source tree -> stays next to guardian_ai/ (existing behaviour)
- inside a zipapp (or any non-writable location) -> ~/.shieldai/
- SHIELDAI_DATA_DIR env var overrides everything
"""
import os
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("SHIELDAI_DATA_DIR")
    if env:
        d = Path(env)
    else:
        here = Path(__file__).resolve().parent
        if here.is_dir():           # normal source tree
            d = here
        else:                       # inside a zipapp: __file__ is not a real dir
            d = Path.home() / ".shieldai"
    d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = ["data_dir"]
