# ShieldAI - project state & handoff

## What this is
Local-first AI control plane. 100% offline. No data leaves the machine.
Pipeline: request -> classify (Router) -> first-principles plan
(FirstPrinciples) -> deterministic execute (Executor) -> optional local
Ollama synthesis (labelled "未検証") -> redact -> sha256 audit chain.

## State (2026-11-07)
- 14 commits on main; working tree clean; 11/11 generated tests PASS.
- Run: `venv/Scripts/python src/main.py` (CLI), `venv/Scripts/python
  src/test_auto.py` (tests), `venv/Scripts/python deploy.py --deploy`
  (zipapp -> dist/shieldai.pyz).
- Only hard dep: `cryptography` (everything else stdlib).

## Environment quirks
- C: drive was ~500MB free -> runtime state lives on D:.
  `SHIELDAI_DATA_DIR=D:\shieldai-data` (setx'd) holds DB + KMS keys.
- Ollama is a portable install at `D:\ollama`; start with
  `start-ollama.cmd` (sets OLLAMA_MODELS + KEEP_ALIVE=24h).
- GPU: RTX A2000 12GB; inference ~6s. Model: qwen2.5:0.5b.
- `llama3.2:1b` pull was stalling on the CDN; if /api/tags later shows
  it, pick_model's llama-family match auto-selects it (no code change).

## Conventions
- Never fabricate: unknowns report verified/unverified/needs_human.
- Secrets are redacted before audit_log (delete > encrypt).
- Generated tests live in src/test_files (regenerated each run; must
  call test() under __main__ so PASS means assertions ran).
- LLM output is inference, never fact - always labelled.
