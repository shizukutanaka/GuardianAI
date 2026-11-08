# Changelog

All notable changes to ShieldAI. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/).

## [1.0.0-rc1] - 2026-11

### Added
- Tamper-evident audit: HMAC chain + signed chain_state + append-only
  triggers; forged work-record detection (tasks + task_queue row_hmac)
- Web dashboard: localhost-only, per-run session token (X-Token),
  CSRF/Origin checks, JA/EN i18n with header selector, aria/focus/
  keyboard-tab a11y, forged table, health badges
- CLI: one-shot argv mode, `--version`/`--help` flags, `verify`,
  `history`, `tasks`, `forged`, `export`, `backup`, `decrypt`,
  `license`, `update`, `diag`, `report`, `doctor`, `ui [ja|en]`
  - `--json` variants on every command
- Distribution: PyInstaller one-file exe (frozen->dashboard),
  SHA256SUMS, CycloneDX SBOM, Inno Setup installer, release.yml
  (tag -> build+test+artifacts on win/macos/ubuntu)
- Licensing: offline Ed25519 license verification +
  vendor keygen (soft enforcement - donation model)
- Observability: crash.log on unhandled exceptions, `diag` support
  info, `report` opt-in pre-filled GitHub issue
- Environment self-check (`doctor`) shared between CLI and UI

### Security
- Web UI requires the per-run session token on every /api/ call
- Noninteractive mode fails closed on a broken audit chain
- Secrets redacted before audit logging

### Notes
- Funding: MIT + GitHub Sponsors only (`.github/FUNDING.yml`)
- The product's only outbound call: `update`/`/api/update` and
  `report` opening a GitHub issue - both user-invoked, read-only

### Post-tag fixes (verified by the first real release run)
- requirements.txt had `python>=3.11` as a package line - release jobs
  failed on all 3 OSes
- release publish needed `contents: write` on GITHUB_TOKEN
- per-OS artifact names (ubuntu/macos uploaded `dist/shieldai` and
  silently overwrote each other); .iss paths were script-relative
- bandit: nosec belongs on the flagged line and inside real comments
  (a `# nosec` inside a triple-quoted string is string content)

### Post-tag additions
- complete i18n - every UI string lives in the JA/EN dict (tabs,
  buttons, badges, tables, stages, toasts, aria-labels, interpolated
  strings via tf())
- CLI i18n - banner, help, warnings, prompts, result display labels
  via SHIELDAI_LANG / --lang / OS locale
- `doctor` + GET /api/doctor + Doctor button - environment self-check
  shared between CLI and UI (crypto / data_dir / db / chain tip /
  ollama / license / network state)
- `update`/`report`/`/api/update` honor SHIELDAI_NO_NETWORK - hard-cut
  for air-gapped installs
- `ui` saves the token URL to data_dir/ui_url.txt - a second launch
  opens the live dashboard instead of crashing on EADDRINUSE
- arrow-key tab navigation + role=tabpanel + th scope + :focus-visible
  (keyboard and screen-reader a11y)
- /api/backup + Backup button - last CLI/UI parity gap
- version shown on status (text), status --json, /api/status, UI badge
- README badges (CI status, release, license, Sponsors) + bug report
  template that asks for `shieldai diag`
- generated test files gitignored - the templates are the source of
  truth
- PyInstaller 64-bit bootloader repaired (C: disk-full partial install
  had wiped it - found by actually rebuilding the exe)
