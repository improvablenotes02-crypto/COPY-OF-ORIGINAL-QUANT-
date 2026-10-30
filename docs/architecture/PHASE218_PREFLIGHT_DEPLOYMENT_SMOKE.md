# Phase 218 — Strict PAPER preflight deployment smoke test

## Purpose

Phase 218 adds `scripts/strict_paper_preflight_smoke.py`, a deployment-facing
smoke check that launches the actual strict PAPER preflight CLI in fresh
subprocesses. It verifies the exact version-1 JSON allowlist and policy values,
checks that unrelated environment secrets are not echoed, and confirms that
`compat` is rejected by the strict preflight route.

## Run

From the extracted project root:

```powershell
python scripts/strict_paper_preflight_smoke.py
```

Expected success marker: `STRICT_PAPER_PREFLIGHT_SMOKE_PASS`.

## Safety boundaries

The smoke check uses `--preflight --json`; it does not build an engine, start
monitoring, connect to a broker, or submit orders. The result validates only
the launcher configuration contract. It is not evidence of live market data,
broker connectivity, strategy profitability, or production readiness. The
legacy `main.py` entrypoint remains unchanged and does not automatically select
the strict launcher.
