# Phase 217 — Strict PAPER preflight schema contract

Phase 217 stabilizes the machine-readable response from the strict PAPER
launcher preflight. JSON output includes `schema_version: 1`, the selected
`strict` profile, and `configuration_validated: true`. Consumers should reject
unknown schema versions rather than infer fields from an unrecognized payload.

The response is intentionally a policy-only allowlist: it reports PAPER mode,
whether the market-data gate is required, the configured max-age threshold,
and explicit `runtime_started: false` / `broker_orders_submitted: false` values.
It does not echo arbitrary environment variables or credentials.

Example:

```powershell
$env:QE_PAPER_DATA_GATE_PROFILE = "strict"
$env:QE_PAPER_DATA_MAX_AGE_SECONDS = "15"
python -m core.runtime.strict_profiled_paper_launcher --preflight --json
```

This is a no-start configuration check, not a market connectivity test, not a
broker authentication test, and not proof that the unchanged legacy `main.py`
uses the strict launcher. Live trading remains outside this phase.
