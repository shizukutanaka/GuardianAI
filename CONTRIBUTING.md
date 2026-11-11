# Contributing

GuardianAI is MIT-licensed and donation-funded via GitHub Sponsors.
Contributions are welcome - the bar is that the product keeps its core
claim: **claims must match behavior**.

## The ground rules (these are not negotiable)

- **Never fabricate**: unknowns report verified / unverified /
  needs_human - never a confident guess.
- **Never overclaim**: "chain ok" means the full chain was verified;
  a tip check says "tip ok". Match words to what actually ran.
- **LLM output is inference**, never fact - always labelled unverified.
- **Local-only**: no network calls except the documented user-invoked
  ones (`update`, `report`). A PR that adds an outbound call will be
  asked to justify it.
- **Secrets are redacted before logging**; prefer deleting over
  encrypting sensitive content.
- **Warnings must reach every surface**: if a state (broken chain,
  forged rows, truncation) is shown in one view, it must be flagged in
  every view and every `--json` variant.
- **Docs must match reality**: if you change a command, update
  README.md and AGENTS.md in the same commit.

## Workflow

1. Fork + branch.
2. `venv/Scripts/python src/test_auto.py` must pass 13/13 (add a
   template to `TEST_NAMES` if you add a subsystem).
3. Keep the stdlib-only + cryptography constraint - new deps need a
   strong reason (the exe and SBOM must stay buildable).
4. Small, honest commits. Describe why, not just what.

## Code layout

- `src/guardian_ai/` - the library (router, first_principles, executor,
  db, compliance, kms, licensing, webui, paths, ollama_inference)
- `src/main.py` - CLI entry (REPL + one-shot argv)
- `src/test_auto.py` - test generator + runner
- `scripts/` - build_exe.py, gen_sbom.py, license_keygen.py,
  shieldai.iss (installer)

## I18n

UI strings live in the `STR` dict in webui.py. Adding a locale is
adding a dict - no other code changes. Keep key parity between locales
(a missing key falls back to English, which is a bug to fix, not a
feature).
