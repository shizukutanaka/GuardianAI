# ShieldAI - Universal AI Control Plane

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
✓ audit_logs: 30+ entries
✓ integrity: ok
✓ agents: 7 (all AgentType values seeded)
✓ tests: 7/7 PASS (assertions actually execute)
```

## Commands
```bash
# Setup (once)
python -m venv venv && venv/Scripts/pip install -r requirements.txt   # Windows
# or: source venv/bin/activate && pip install -r requirements.txt      # POSIX

# Interactive CLI
venv/Scripts/python src/main.py   # Windows (or: python src/main.py after activating venv)

# Run tests (generates src/test_files/test_*.py, then executes them)
venv/Scripts/python src/test_auto.py

# Check health
python -c "import sqlite3; conn=sqlite3.connect('src/guardian_ai/shield_ai.db'); c=conn.cursor(); c.execute('SELECT COUNT(*) FROM audit_logs'); print('audit_logs:', c.fetchone()[0]); c.execute('PRAGMA integrity_check'); print('integrity:', c.fetchone()[0])"
```

## License
MIT
