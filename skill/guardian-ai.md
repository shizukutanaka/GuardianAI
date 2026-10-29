---
tags: [privacy, enterprise, local-llm, agent, security, offline]
category: software-development
status: v1.0.0
name: guardian-ai
description: Use for 100% local enterprise AI agents with zero external data.
---

## Guardian AI - Privacy-First Enterprise Agent Platform

### Architecture

GUI -> Agent Router -> [Accounting | Legal | HR | IT | Developer | Medical | General Agent]
                     v
              Model Selector (llama3:8b/70b, qwen2:72b)
                     v
              MCP Servers (Git/SQL/Office/Filesystem/Browser)

### Core Components

1. Agent Router (`src/guardian_ai/router.py`)
   - Classify requests into 7 agent types
   - Estimate complexity (simple/medium/complex)
   - Select model based on complexity
   - Decompose tasks

2. Agent Connector (`src/guardian_ai/connector.py`)
   - Connect multiple agents in parallel
   - Aggregate results

3. Model Selector (`config/model_selector.yaml`)
   - Auto/manual model switching
   - Performance tuning

### Key Features

- Zero External Data: All processing 100% local
- Network Disruption Tolerant: Works offline on LAN
- Zero Trust: RBAC, AD/LDAP integration
- Audit Trail: Full prompt/execution/result logging
- Secret Management: Windows Credential Manager/TPM
- Data Anonymization: PII redaction before processing

### Tech Stack

- Python 3.11+
- llama-cpp-python (llama3:8b, 70b, qwen2:72b)
- SQLite (audit logs)
- MCP (Model Context Protocol)

### Running

PYTHONPATH=src python src/main.py

### Testing

PYTHONPATH=src python src/guardian_ai/test_router.py

Status: All tests passing. Multiple agents + model selection verified.
