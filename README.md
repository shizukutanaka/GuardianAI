# ShieldAI - Universal AI Control Plane

## Overview
ShieldAI is an intelligent AI control plane system with automated audit logging, agent routing, and compliance monitoring.

## Architecture
- **Router**: 7-agent classification system (accounting, legal, HR, IT, developer, medical, general)
- **Encryption**: AES-256-GCM + TPM/KMS integration
- **Audit Trail**: SOC2-compliant logging
- **Compliance**: GDPR/ISO27001 automated checks

## Health Status
```
✓ audit_logs: 19 entries
✓ integrity: ok
✓ agents: 3 (accounting, legal, general)
✓ tests: 4/4 PASS (100%)
```

## Commands
```bash
# Run all agents
python src/main.py

# Run tests
python src/test_auto.py --all --report

# Check health
python -c "import sqlite3; conn=sqlite3.connect('src/guardian_ai/shield_ai.db'); c=conn.cursor(); c.execute('SELECT COUNT(*) FROM audit_logs'); print('audit_logs:', c.fetchone()[0]); c.execute('PRAGMA integrity_check'); print('integrity:', c.fetchone()[0])"
```

## License
MIT
