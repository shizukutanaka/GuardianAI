# ShieldAI Commercial License — DRAFT for legal review

> **Status: proposal, not effective.** This is a working draft for the
> business decision on how ShieldAI is sold. It is not legal advice and
> must be reviewed by counsel before any repo license file is changed.
> The repo currently carries **no LICENSE file at all** — that itself is
> a decision that needs making.

## The decision being made

The product's core claim is *"a tamper-evident audit trail you can
verify yourself."* That claim is most credible when customers can read
the code that makes it. So the natural fit is a **source-available**
model — code stays visible, commercial use requires a license:

| Option | Fits the claim? | Revenue impact |
|--------|----------------|----------------|
| MIT/Apache (fully OSS) | Weakest — anyone can re-sell the audit product | No enforcement |
| **Source-available (e.g. BSL-style)** | **Strongest — claims verifiable, commercial use gated** | Perpetual/seat sales viable |
| Dual license (OSS + commercial) | Medium — needs CLA infrastructure | Enterprise upsell |
| Closed source | Hurts the verifiability claim | Most control |

## Proposed terms (source-available, BSL-style)

1. **Grant**: view, audit, and modify the source for internal
   evaluation. Production use requires a signed license file
   (verified offline by `guardian_ai/licensing.py` — no activation
   server, consistent with the local-only claim).
2. **Per-seat**: each `shieldai.license` covers N seats; the license
   file is Ed25519-signed and machine-checkable.
3. **No redistribution**: compiled or source redistribution requires
   written permission.
4. **Support window**: perpetual license + 12-month maintenance for
   updates (renewable), matching standard on-prem models.
5. **Audit rights — inverse**: the *customer* may audit the vendor's
   code freely; this is the product's selling point, not a concession.
6. **No warranty** / limitation of liability (standard commercial terms).
7. **Privacy**: the software transmits nothing — no telemetry, no
   activation phone-home. Any support channel is opt-in by the user.
8. **Change date (optional, BSL pattern)**: each release converts to
   Apache-2.0 after N years — a credible promise to regulated buyers
   worried about vendor lock-in.

## What remains undecided (needs the owner)

- [ ] Exact license form (BSL text vs custom EULA)
- [ ] Price model (perpetual-per-seat? maintenance %?)
- [ ] Whether existing public history needs relicensing/copyright line
- [ ] Company name for the license grant
- [ ] Support channel + SLA terms
- [ ] Change-to-OSS date, if any
