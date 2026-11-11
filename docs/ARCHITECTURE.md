# GuardianAI Architecture

Local-first AI control plane. 100% offline - no data leaves the machine
(the sole exception: `update`/`report`/`/api/update`, user-invoked,
read-only).

## System overview

```
┌─────────────────────────────────────────────────────────────────┐
│  FRONTEND                                                       │
│  ┌─────────────────────┐  ┌─────────────────────────────────┐  │
│  │ Web Dashboard       │  │ CLI (shieldai.pyz / exe / src)  │  │
│  │ localhost:8765      │  │ interactive REPL + one-shot      │  │
│  │ ?t=<token>          │  │ argv commands                    │  │
│  │ X-Token header      │  │ --json / --lang <lang>           │  │
│  │ ?lang=ja|en          │  │ --version / --help               │  │
│  │ sessionStorage      │  │ config <key> <value>             │  │
│  └─────────────────────┘  └─────────────────────────────────┘  │
│           │                            │                        │
└───────────┼────────────────────────────┼────────────────────────┘
            │                            │
            ▼                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER                                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  main.py - command dispatch + i18n + crash handler      │    │
│  │  cmd -> handler -> audit -> display                     │    │
│  └─────────────────────────────────────────────────────────┘    │
│           │                            │                        │
│           ▼                            ▼                        │
│  ┌─────────────────┐        ┌──────────────────────┐            │
│  │ Router          │        │ webui.py             │            │
│  │ classify agent  │        │ 127.0.0.1:8765      │            │
│  │ (it/legal/...)   │        │ GET/POST handlers    │            │
│  │ complexity       │        │ token auth + CSRF    │            │
│  └─────────────────┘        └──────────────────────┘            │
│           │                            │                        │
│           ▼                            ▼                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ FirstPrinciples - question assumptions, identify        │    │
│  │ fundamentals/unknowns, produce a shortest task chain    │    │
│  └─────────────────────────────────────────────────────────┘    │
│           │                                                     │
│           ▼                                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Executor - deterministic local execution                │    │
│  │  ingest local files -> extract evidence -> verify       │    │
│  │  -> optional LLM synthesis (labelled as inference)      │    │
│  │  -> unknowns for local verification, never guess        │    │
│  └─────────────────────────────────────────────────────────┘    │
│           │                            │                        │
│           ▼                            ▼                        │
│  ┌─────────────────┐        ┌──────────────────────┐            │
│  │ OllamaClient    │        │ Compliance          │            │
│  │ localhost only   │        │ redact secrets       │            │
│  │ http://127.0.0.1 │        │ detect PII/keys      │            │
│  │ pick_model       │        │ integrity checks     │            │
│  └─────────────────┘        └──────────────────────┘            │
│           │                            │                        │
└───────────┼────────────────────────────┼────────────────────────┘
            │                            │
            ▼                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  db.py - SQLite append-only audit trail                 │    │
│  │  audit_logs | task_queue | tasks | agents               │    │
│  │  chain_state (HMAC head+count) | signatures             │    │
│  │  verify_audit_chain | export_audit | backup_db          │    │
│  └─────────────────────────────────────────────────────────┘    │
│           │                            │                        │
│           ▼                            ▼                        │
│  ┌─────────────────┐        ┌──────────────────────┐            │
│  │ KMS             │        │ Paths               │            │
│  │ encryption.py    │        │ data_dir()           │            │
│  │ local keys       │        │ SHIELDAI_DATA_DIR    │            │
│  │ export decrypt   │        │ backups/ .enc .key   │            │
│  └─────────────────┘        └──────────────────────┘            │
│           │                            │                        │
│           ▼                            ▼                        │
│  ┌─────────────────┐        ┌──────────────────────┐            │
│  │ Files           │        │ Config               │            │
│  │ crash.log        │        │ config.json          │            │
│  │ shieldai.license │        │ lang / no_network    │            │
│  │ ui_url.txt       │        │ persisted prefs      │            │
│  │ backups/*.db     │        │                      │            │
│  └─────────────────┘        └──────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

## Request lifecycle

```
request
  ├─ CLI: 'shieldai <request>' or REPL
  ├─ Web: POST /api/request {request}
  │
  ▼
Router.analyze(request)
  │  agent: accounting|legal|hr|it|developer|medical|general
  │  complexity: low|medium|high
  │  model: ollama model name (for synthesis, optional)
  │
  ▼
FirstPrinciples.question(request, agent, complexity)
  │  assumptions_to_question: list[str]
  │  fundamentals: list[str] (what's verifiable)
  │  unknowns: list[str] (what can't be verified locally)
  │  task_chain: [{id, type, desc}] - shortest path
  │
  ▼
Executor.execute(request, plan, agent, model)
  │  for step in plan.task_chain:
  │    step.type == 'ingestion':
  │      local files or pasted text -> source_text
  │    step.type == 'extraction':
  │      deterministic pattern extraction (keyword/regex)
  │      -> evidence list (never fabricate)
  │    step.type == 'verification':
  │      verify unknowns against source_text
  │      -> verified/unverified/needs_human
  │    step.type == 'synthesis':
  │      LLM output (optional, local Ollama only)
  │      -> always labelled as 'inference, not fact'
  │    step.type == 'audit':
  │      log to audit_logs (HMAC chain + signature)
  │
  ▼
Compliance.redact(answer)  # remove secrets before audit
Audit.log(agent, request, result, complexity, model)
  │  chain_state = HMAC(prev_chain_state + entry)
  │  signature = Ed25519(task_data)
  │
  ▼
Output
  ├─ CLI: Agent:/Model:/Complexity:/Plan:/answer/unknowns/
  │        [audit_logs #N]
  ├─ Web: result.body + evidence + unknowns displayed
  │
  ▼
Observability
  ├─ status --json / /api/status: integrity + queue stats + version
  ├─ verify --json / /api/verify: chain ok/broken/forged
  ├─ verify <file> [--json]: external backup verification
  ├─ history --json / /api/history: audit log table
  ├─ tasks --json / /api/tasks: work record table
  ├─ forged --json / /api/forged: forged work-record rows
  ├─ doctor [--json] / /api/doctor: 8-check environment diag
  ├─ export --json / /api/export: encrypted .enc export
  ├─ backup --json / /api/backup: VACUUM INTO + rotation
  ├─ decrypt --json / /api/decrypt: decrypt + verify export
  ├─ license [--json] / /api/license: status + verify
  ├─ update [--json] / /api/update: GitHub release check
  │        + release notes (user-invoked, read-only)
  ├─ report [--json] / /api/report: pre-filled GitHub issue
  ├─ config [key] [value]: persist lang/no_network
  └─ ui [ja|en]: open dashboard in that locale
```

## Frontend design

```
Web Dashboard (webui.py)
  Port:        127.0.0.1:8765 (fixed - ui_url.txt + docs reference it)
  Auth:        per-run session token
               ?t= in the URL is read into sessionStorage('st'),
               sent as X-Token header on every fetch
  CSRF:        POST requires Origin/Referer headers
  i18n:        ?lang=ja|en -> sessionStorage -> navigator.language
               -> STR dict -> data-i18n attribute on static HTML
               -> t()/tf() for dynamic strings
  A11y:        lang=, aria-selected, th scope=col, role=tabpanel,
               arrow-key tab nav, :focus-visible
  Theme:       dark theme (design tokens in CSS vars)
  Layout:      responsive grid (3-col -> 1-col on mobile)
  Health:      polling /api/status + /api/doctor every 5s
               badges: version, chain tip ok, ollama up,
               license (community/licensed), network state
  Tabs:        Requests | Tasks | Audit | Forged
  Actions:     Doctor | Check updates | Verify | Export | Decrypt
               Backup | Report issue
  Toast:       result feedback (success/error/info)
  Offline:     SHIELDAI_NO_NETWORK or config no_network=on
               blocks /api/update -> 'outbound calls disabled'

CLI (main.py)
  REPL:        no argv -> interactive loop with shieldai@> prompt
  One-shot:    'shieldai <cmd> [args]' runs once and exits
  Flags:       --version/-v --help/-h --lang <lang>
  i18n:        _cli_lang(): SHIELDAI_LANG -> --lang -> config.json
               -> OS locale -> 'en'
               _CLI_STR dict + _t()/tf() for warnings/labels
  Commands:    <request> history tasks status verify forged
               export backup decrypt license version update
               diag report doctor ui config help quit
  Output:      Agent:/Model:/Complexity:/Plan:/evidence/
               unknowns/[audit_logs #N]
  --json:      every command emits JSON for scripting
  Crash:       exception -> write crash.log + friendly message
               diag command shows version/OS/python/last crash
  Console:     chcp 65001 + UTF-8 reconfigure on Windows
               so JA strings don't render as mojibake on cp932
```

## Backend design

```
Router (router.py)
  Input:   request text
  Output:  {agent, model, complexity}
  Method:  keyword pattern matching + file path detection
  Agents:  accounting legal hr it developer medical general
  Decision: agent = best keyword match or 'general'

FirstPrinciples (first_principles.py)
  Input:   request, agent, complexity
  Output:  {questioned, fundamentals, unknowns, task_chain}
  Method:  identify what's verifiable vs what's inferred
  Task chain: ingestion -> extraction -> verification ->
              synthesis -> audit (deterministic shortest path)

Executor (executor.py)
  Input:   request, plan, agent, model
  Output:  {answer, evidence, unknowns, execution_time}
  Method:  deterministic local execution:
    ingestion:   local file paths -> read into source_text
    extraction:  regex/keyword patterns on source_text
                 -> evidence list (deterministic, never fabricate)
    verification: verify unknowns against source_text
                 -> verified/unverified/needs_human
    synthesis:    optional LLM call (ollama only, localhost)
                 -> labelled 'inference, not fact' always
    audit:        log entry -> db.py (HMAC chain)

OllamaClient (ollama_inference.py)
  Host:    http://127.0.0.1:11434 (hardcoded localhost - the
           '100% offline' claim requires it stays local)
  Scheme:  http/https only (rejects file://, gopher://, etc.)
  pick_model: prefer loaded model to avoid load/swap stall
  Models:  qwen2.5:0.5b, llama3.2:1b (installed)

Compliance (compliance.py)
  Redact:   regex patterns for API keys, tokens, passwords
            -> '[REDACTED]' before audit_log
  Detect:   API key patterns (AKIA, ghp_, xoxb, sk-, etc.)
            PII patterns (email, phone, SSN, etc.)
  doctor_checks(): crypto/data_dir/db/chain tip/ollama/
                   license/network/config readability
  Integrity: quick_check (schema + row count) + deep_check

DB (db.py)
  Engine:  SQLite (append-only audit trail)
  Tables:  audit_logs | task_queue | tasks | agents
           chain_state | signatures
  Chain:   chain_state = HMAC(prev + entry) - tip only check
  Verify:  verify_audit_chain(conn) -> ok/broken_at/
           forged_tasks/triggers_missing/entries
  Export:  export_audit(conn, dest) -> encrypted .enc file
  Backup:  VACUUM INTO dst + rotate latest 10

KMS (encryption.py + kms.py)
  Keys:    local Ed25519 keypair (signing) + AES key (encrypt)
           stored in SHIELDAI_DATA_DIR/.shield_keys
  Export:  encrypt .enc file with AES key
  Decrypt: verify signature + decrypt with local key
  Chain:   chain_state uses KMS key for HMAC

Paths (paths.py)
  data_dir(): SHIELDAI_DATA_DIR or default
              holds DB, KMS keys, crash.log, shieldai.license,
              ui_url.txt, config.json, backups/
  backup_dir(): data_dir/backups/

Config (config.json in data_dir)
  lang:           'ja'|'en' - persisted UI/CLI language
  no_network:     'on'|'off' - blocks all outbound calls
```

## Security model

```
Auth:        per-run session token on the loopback web UI
             delivered only via the browser URL (?t=) -
             any local process can read the URL but the token
             is generated per-server-run (not persisted)
CSRF:        POST requires Origin/Referer headers
             (blocks cross-site form posts to /api/request)
Secrets:     redact() before audit_log - API keys, tokens,
             passwords are replaced with '[REDACTED]'
             (delete > encrypt > redact order for max safety)
Audit chain: chained HMAC - chain_state = HMAC(prev + entry)
             only the tip is checked (not full verification -
             'chain ok' means 'tip ok', not 'all rows verified')
Task sigs:   Ed25519 signature on task_queue + tasks data
             forged = invalid/unsigned signature (not 'tampered')
Outbound:    only update/report/api-update - user-invoked,
             read-only, sends nothing, no auto-update
             (downgrade/spoofing channel if unsigned)
Localhost:   Ollama + web UI bound to 127.0.0.1 only -
             no remote connections possible
Token:       web UI token generated per-server-run, delivered
             only via the browser URL - not stored in a file
             (ui_url.txt holds the token but that's local)
```

## Key design decisions

```
1. 100% local-only by default
   Ollama host is hardcoded localhost - configurable would
   break the 'offline' claim (LLM calls would leave the machine)

2. No auto-update
   unsigned binary + remote fetch = downgrade/spoofing channel
   update is user-invoked read-only, never silent

3. Append-only audit
   SQLite + chained HMAC + Ed25519 signatures on tasks
   'chain ok' means 'tip ok', not 'all rows verified' (honest)

4. Deterministic > LLM
   the deterministic executor is the core value - LLM synthesis
   is optional, always labelled as inference (never fact)
   pick_model prefers loaded models to avoid load stalls

5. Evidence > inference
   the pipeline shows evidence (extracted patterns) separately
   from unknowns (needs local verification) - never fabricate

6. Fail-closed
   broken chain -> refuse writes (warn + abort)
   unknown -> needs_human (don't guess)
   no evidence -> 'evidence_missing' (don't fabricate)

7. Single source of truth
   _CLI_STR dict for all CLI i18n
   STR dict + data-i18n for all UI i18n
   config.json for user preferences (lang/no_network)
   help text = AGENTS.md command list (not duplicated)

8. Files-in-data-dir
   SHIELDAI_DATA_DIR holds everything - DB, keys, config,
   backups, crash.log, ui_url.txt, shieldai.license
   (project dir is clean, runtime state is on D:)

9. Files-in-repo
   tests auto-generate (src/test_files gitignored)
   docs sync with code (AGENTS.md/README/BUILD/CHANGELOG)
   generated tests must call test() under __main__
```

## Boundaries (what the product deliberately does NOT do)

```
- No telemetry/analytics (crashes go to local crash.log only)
- No external LLM calls (Ollama is hardcoded localhost)
- No cloud sync (local SQLite only)
- No auto-update (unsigned binary + remote = spoofing channel)
- No remote backup (backup is local VACUUM INTO)
- No restore command (destructive - manual file copy)
- No ollama_host config (localhost-only by design)
- No ollama_model config (pick_model auto-selects loaded)
- No data_dir config (existing KMS keys/DB would be orphaned)
- No ui_port config (fixed 8765 is referenced everywhere)
- No persisted results beyond audit_logs (ephemeral by design)
```

## Verification surface

```
verify <file> [--json]
  opens the file read-only and runs the same verify_audit_chain
  - a tampered-or-outdated backup fails (not silently trusted)

verify [--json]
  runs the full chain verify on the live DB
  (tip check for speed: chain_state head+count vs last row)

verify --json
  machine-readable verify (ok/broken/forged as JSON)

  Verification is tip-only (chain_state head+count)
  - 'chain ok' means the HEAD matches, not every row checked
  - deep verify would re-hash every row (slower but complete)
```

## Observability surface

```
doctor [--json] / GET /api/doctor
  cryptography | data_dir writable | database | chain tip |
  ollama | license | network | config readability
  each check returns ok + detail - failures say WHY

status [--json] / GET /api/status
  version + audit_entries + agents + queue stats +
  chain tip + triggers_missing + ollama + license + network

diag [--json] / /api/diag (CLI only)
  version + OS + python + arch + frozen + data_dir + last crash

report [--json] / /api/report
  opt-in GitHub issue with diag + crash info (never auto-sends)

update [--json] / /api/update
  GitHub Releases check (user-invoked, read-only)
  + release notes + url (no silent download/install)

export [--json] / /api/export
  encrypted .enc export (all audit entries + work record)

backup [--json] / /api/backup
  VACUUM INTO + keep latest 10 (rotation)

decrypt <file> [--json] / /api/decrypt
  decrypt .enc + verify signature + verify chain

history [--json] / /api/history
  latest N audit entries (default 10)

tasks [--json] / /api/tasks
  task_queue + tasks (latest 20, forged marked)

forged [--json] / /api/forged
  forged work-record rows (invalid/unsigned signatures)

config [key] [value]
  persist lang/no_network to data_dir/config.json

ui [ja|en]
  open the dashboard in that locale
  (second launch opens via ui_url.txt, no port conflict)
```

## File map

```
src/
  main.py                    CLI + command dispatch + i18n + crash
  guardian_ai/
    router.py                request -> agent + complexity + model
    first_principles.py      assumptions -> fundamentals -> tasks
    executor.py              deterministic execute + evidence +
                             LLM synthesis (labelled) + unknowns
    ollama_inference.py      local Ollama HTTP client (localhost)
    compliance.py            redact secrets + detect PII +
                             integrity checks + doctor_checks()
    db.py                    SQLite audit chain + export + verify +
                             backup + signatures
    encryption.py            local Ed25519 + AES keys
    kms.py                   key management (local)
    licensing.py             Ed25519 license verify (offline)
    local_search.py          local file ingestion
    paths.py                 data_dir + backup_dir
    webui.py                 localhost dashboard server + API +
                             i18n + a11y + token auth + CSRF
  test_auto.py               generated test runner + templates
  test_files/                generated tests (gitignored)
  test_reports/              generated test reports (gitignored)

scripts/
  build_exe.py               PyInstaller build + self-check
  gen_sbom.py                CycloneDX SBOM generator
  license_keygen.py          Ed25519 license key generator
  shieldai.iss               Inno Setup installer script

deploy.py                    zipapp build + self-check + --exe

docs/
  ARCHITECTURE.md            this file
  COMMERCIAL-LICENSE-DRAFT.md
  screenshot.png             dashboard screenshot

manifests/s/ShieldAI/...     winget manifest (version, installer,
                             en-US, ja-JP)

.github/
  workflows/
    test.yml                 run tests on push/PR
    ci.yml                   bandit + tests on push/PR
    release.yml              tag -> build all -> publish release
  FUNDING.yml                GitHub Sponsors
  ISSUE_TEMPLATE/
    bug_report.yml           structured bug report + diag field
    feature_request.yml      'does it keep claims honest' check
  PULL_REQUEST_TEMPLATE.md   honesty check + test plan
  CODEOWNERS                 @shizukutanaka
  dependabot.yml             weekly pip dep scan

LICENSE                      MIT license text
SECURITY.md                  vuln reporting policy
CODE_OF_CONDUCT.md           contributor covenant
CONTRIBUTING.md              dev guide
CHANGELOG.md                 version history
AGENTS.md                    handoff + env quirks + conventions
README.md                    intro + usage + commands + badges
BUILD.md                     build docs
requirements.txt             runtime deps (cryptography only)
requirements-dev.txt         dev deps (pytest etc.)
```
