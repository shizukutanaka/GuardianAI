# Security Policy

ShieldAI is a local-first product - its attack surface is the local
machine and the loopback web UI (127.0.0.1 only, per-run session token).

## Reporting a vulnerability

Please do NOT open a public issue for security reports. Report via
GitHub's private vulnerability reporting (Security tab -> "Report a
vulnerability") or open an issue marked `[security]` with minimal
detail and we will follow up privately.

Include: version (`shieldai version`), OS, whether the binary is frozen
(exe) or run from source, and a minimal reproduction.

## What counts

- Audit-chain bypass: tampering that verify does not detect
- Token/CSRF bypass on the web UI
- Secret redaction gaps (a credential pattern that leaks into the log)
- RCE / path traversal / injection reachable from the request pipeline
- Dependency vulnerabilities in `cryptography`

## Out of scope (by design)

- Localhost trust assumptions documented as boundaries (a hostile
  process with local code execution can already reach most of the
  machine - the session token mitigates, it cannot fully isolate)
- Regex-based secret detection misses novel formats (documented
  boundary - delete-over-encrypt is the mitigation)
- The `update`/`report` commands contacting GitHub when explicitly
  invoked by the user (the product's only outbound call)
- Issues requiring physical access or admin rights on the machine

## Response

- Acknowledged: within a few days
- Fixed on `main` after verification; disclosed with the release notes
