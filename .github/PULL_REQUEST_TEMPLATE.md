## Summary
<!-- what does this change, and why? -->

## Honesty check (required)
<!-- ShieldAI's core claim is that claims match behavior. Answer: -->
- [ ] This change does not overclaim (e.g. "chain ok" only on a tip
      check is honest; claiming "verified" without running the full
      check is not)
- [ ] This change does not broaden the local-only claim (any outbound
      call is user-invoked and read-only, documented here)
- [ ] LLM output, if any, is labelled as inference, never fact
- [ ] Secrets are redacted before they reach the audit trail

## Test plan
<!-- `venv/Scripts/python src/test_auto.py` must be 13/13 PASS;
     for behavior changes, a generated test that actually calls test() -->
- [ ] `venv/Scripts/python src/test_auto.py` passes
- [ ] For new features: the change is exercised by a generated test,
      or the honest-boundary case is documented (e.g. a frozen-exe
      boundary that can't reach test_auto.py)
