# ShieldAI - Universal AI Control Plane

[![Test Runner](https://github.com/shizukutanaka/GuardianAI/actions/workflows/test.yml/badge.svg)](https://github.com/shizukutanaka/GuardianAI/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/shizukutanaka/GuardianAI)](https://github.com/shizukutanaka/GuardianAI/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-ff69b4)](https://github.com/sponsors/shizukutanaka)

Free, local-first, donation-supported. If ShieldAI is useful to you:
[sponsor it on GitHub](https://github.com/sponsors/shizukutanaka).

## Overview
ShieldAI is a local-first AI control plane: classify a request, pick an agent,
build a first-principles task plan, and audit everything. 100% offline - no
data leaves the machine.

## Architecture
- **Router**: 7-agent classification (accounting, legal, HR, IT, developer, medical, general)
- **First Principles**: every request is stripped of assumptions, reduced to
  verifiable fundamentals, unknowns are named, and the shortest task chain is
  reconstructed (`guardian_ai/first_principles.py`)
- **Executor**: plans actually run - ingestion (local files), deterministic
  per-agent extraction, unknown verification against source text, synthesis
  (`guardian_ai/executor.py`). Medical requests with PHI patterns are blocked
  before extraction.
- **LLM (optional)**: local Ollama daemon only (`guardian_ai/ollama_inference.py`,
  stdlib HTTP). When reachable it fills in the synthesis step using verified
  evidence only; output is labelled as model inference, never fact.
- **Encryption**: AES-256-GCM with authenticated tag verification; keys managed
  locally via env var or Windows DPAPI (`guardian_ai/kms.py`)
- **Audit Trail**: SQLite `audit_logs` with FK-enforced agent names; the full
  thought path (assumptions / fundamentals / unknowns / plan) is stored per request
- **Compliance**: verifiable local checks only - audit DB integrity and
  sensitive-data scanning (`guardian_ai/compliance.py`)

## Health Status
```
✓ integrity: ok (HMAC chain + chain_state + append-only triggers,
  tamper-evident; work records signed)
✓ agents: 7 (all AgentType values seeded)
✓ tests: 13/13 PASS (assertions actually execute; includes a main.py
  import check)
```

## Usage examples

Type a request at the `shieldai@>` prompt — keywords pick the agent
automatically (Japanese or English):

```
契約書の法律リスク          -> legal     (obligation/penalty extraction)
サーバー障害 ERROR 10.0.0.1  -> it        (error/timestamp/host extraction)
決算書の仕訳 1,000,000円     -> accounting (figures/periods/accounts)
履歴書 5年経験 スキル         -> hr        (experience/skills/claims)
カルテの症状 体温38度         -> medical   (measurements; PHI-blocked if secrets found)
git のバグ修正テスト          -> developer (code blocks/file refs/commands)
一般事務処理                -> general   (dates/quantities)
```

Reference a local file by name (e.g. `契約書.txt`) to pull its contents
into ingestion. Output = deterministic verified result + optional
`[LLM 推論]` model synthesis (labelled unverified).

## Commands
```bash
# Setup (once)
python -m venv venv && venv/Scripts/pip install -r requirements.txt   # Windows
# or: source venv/bin/activate && pip install -r requirements.txt      # POSIX

# Interactive CLI
venv/Scripts/python src/main.py   # Windows (or: python src/main.py after activating venv)

# Run tests (generates src/test_files/test_*.py, then executes them)
venv/Scripts/python src/test_auto.py

# Deploy: build a single-file zipapp (stdlib-only, no cloud)
venv/Scripts/python deploy.py --deploy   # -> dist/shieldai.pyz
# or a standalone exe (no Python needed on the target machine):
venv/Scripts/python scripts/build_exe.py # -> dist/shieldai.exe + SHA256SUMS.txt

# CLI commands inside main.py (also one-shot: `python src/main.py <command>`):
#   history [N], tasks, status, verify, forged, export, backup,
#   decrypt FILE, license [FILE], version, update, diag, report,
#   doctor, ui [ja|en], help, quit
#   every command supports --json for scripting
#   conventional flags work too: --version / -v / --help / -h

# Check health
python -c "import sqlite3; conn=sqlite3.connect('src/guardian_ai/shield_ai.db'); c=conn.cursor(); c.execute('SELECT COUNT(*) FROM audit_logs'); print('audit_logs:', c.fetchone()[0]); c.execute('PRAGMA integrity_check'); print('integrity:', c.fetchone()[0])"
```

## License
MIT - see [LICENSE](LICENSE). Community conduct:
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security:
[SECURITY.md](SECURITY.md) + `.well-known/security.txt`.
