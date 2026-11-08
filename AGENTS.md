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
The authoritative list is `shieldai help` / `--help` - DO NOT hardcode
it here (this list went stale twice when features landed). Notes:
- `--lang ja|en` localizes banner/help/warnings (SHIELDAI_LANG env,
  '--lang', config.json, or OS locale in that order - `config lang xx`
  persists it); `shieldai ui` without an arg opens the dashboard in
  the persisted locale; `--json` on every command
- `config` persists user prefs to data_dir/config.json - `lang <ja|en>`
  and `no_network <on|off>` (env SHIELDAI_NO_NETWORK is the other source)
- the Ollama host is deliberately hardcoded to localhost - making it
  configurable would break the '100% offline' claim (LLM calls would
  leave the machine)
- `ui` writes data_dir/ui_url.txt - a second launch opens the live
  dashboard instead of crashing on EADDRINUSE
- doctor's checks live in guardian_ai/compliance.py::doctor_checks
  (shared with GET /api/doctor)

## Environment quirks
- SHIELDAI_DATA_DIR=D:\shieldai-data (setx'd) holds DB + KMS keys +
  crash.log + shieldai.license + ui_url.txt + config.json.
- Ollama portable at D:\ollama; start with `start-ollama.cmd`.
- GPU: RTX A2000 12GB; inference ~6s; deterministic mode works w/o GPU.
- venv is a 32-bit Python - if cryptography's _rust DLL breaks,
  force-reinstall: `venv/Scripts/python -m pip install
  --force-reinstall --no-cache-dir "cryptography>=41,<46"`.
- SHIELDAI_NO_NETWORK=1 closes the only outbound call (update/report/
  /api/update) - hard-cut for air-gapped installs.
- PyInstaller 64-bit bootloader can be missing after a C: disk-full
  partial install - repair by extracting it from the wheel into
  venv/Lib/site-packages/PyInstaller/bootloader/Windows-64bit-intel/.
- D:\pyi-tmp has an irremovable empty dir (FS quirk - harmless).

## Conventions
- Never fabricate: unknowns report verified/unverified/needs_human.
- Secrets are redacted before audit_log (delete > encrypt).
- Broken/forged data is never silently touched: every read/write path
  (history/tasks/export/backup/--json) warns or flags.
- Generated tests live in src/test_files (regenerated each run; must
  call test() under __main__ so PASS means assertions ran).
- Web UI: localhost-only, per-run session token (X-Token) required on
  every /api/ call; JA/EN i18n via ?lang= / header dropdown.
