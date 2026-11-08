# ShieldAI - project state & handoff

## What this is
Local-first AI control plane. 100% offline. No data leaves the machine
(the sole exception: `update`/`/api/update` checks GitHub Releases -
user-invoked, read-only).
Pipeline: request -> classify (Router) -> first-principles plan
(FirstPrinciples) -> deterministic execute (Executor) -> optional local
Ollama synthesis (labelled "未検証") -> redact -> HMAC audit chain.

## State (2026-11-08)
- main pushed continuously to GitHub (shizukutanaka/GuardianAI);
  13/13 generated tests PASS (includes test_main.py - imports the CLI
  entry point so a broken main.py can't ship silently).
- Funding model: MIT + GitHub Sponsors only (`.github/FUNDING.yml`).
- Version: `__version__` in `src/guardian_ai/__init__.py`.

## Run / build
- CLI (dev): `venv/Scripts/python src/main.py`
- One-shot: `python src/main.py <command>` - banner/goodbye suppressed,
  clean `--json` output. Flags `--version`/`-v`/`--help`/`-h` map to
  commands (they are NOT analyzed as requests).
- Tests: `venv/Scripts/python src/test_auto.py` (generates
  src/test_files/test_*.py, then executes each).
- zipapp: `venv/Scripts/python deploy.py --deploy` -> dist/shieldai.pyz
- standalone exe (no Python on target): `venv/Scripts/python
  scripts/build_exe.py` -> dist/shieldai.exe + SHA256SUMS.txt.
  Frozen exe with no args launches `ui` (product behaviour); data dir
  moves to %LOCALAPPDATA%\ShieldAI (temp extraction dirs get wiped).
- SBOM: `venv/Scripts/python scripts/gen_sbom.py` ->
  dist/sbom.cyclonedx.json (CycloneDX 1.5).
- Release: `git tag v*` -> `.github/workflows/release.yml` runs tests,
  builds exe+SBOM+sums on windows/macos/ubuntu, Inno Setup installer on
  Windows (`scripts/shieldai.iss`), attaches all to a GitHub Release.
- Licenses: `scripts/license_keygen.py init|sign` - Ed25519 vendor key
  lives in gitignored `.vendor/` (never commit it).

## CLI commands
history [N|--json N], tasks [--json], status [--json], verify [--json],
forged [--json], export [--json], backup [--json], decrypt [--json] FILE,
license [FILE|--json], version [--json], update [--json], diag [--json],
report [--json], ui, help, quit.

## Environment quirks
- SHIELDAI_DATA_DIR=D:\shieldai-data (setx'd) holds DB + KMS keys +
  crash.log + shieldai.license.
- Ollama portable at D:\ollama; start with `start-ollama.cmd`.
- GPU: RTX A2000 12GB; inference ~6s; deterministic mode works w/o GPU.
- venv is a 32-bit Python - if cryptography's _rust DLL breaks,
  force-reinstall: `venv/Scripts/python -m pip install
  --force-reinstall --no-cache-dir "cryptography>=41,<46"`.

## Conventions
- Never fabricate: unknowns report verified/unverified/needs_human.
- Secrets are redacted before audit_log (delete > encrypt).
- Broken/forged data is never silently touched: every read/write path
  (history/tasks/export/backup/--json) warns or flags.
- Generated tests live in src/test_files (regenerated each run; must
  call test() under __main__ so PASS means assertions ran).
- Web UI: localhost-only, per-run session token (X-Token) required on
  every /api/ call; JA/EN i18n via ?lang= / header dropdown.
