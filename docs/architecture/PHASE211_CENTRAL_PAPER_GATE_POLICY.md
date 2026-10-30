# Phase 211 — Central paper data-gate policy

## Changes

- Added `core.exchanges.paper_data_gate_policy.validate_paper_data_gate_config` as the shared validator for required/optional gate configuration.
- Added `market_data_gate_required=False` to `RealTimeEngine` and `PaperRuntime` construction.
- With `market_data_gate_required=True`, construction fails closed unless a finite, non-negative `market_data_max_age_seconds` is supplied. The requirement is propagated by `RealTimeEngine` to each newly created `PaperRuntime`.
- Default remains `False` to preserve existing callers. This phase does not silently enable a global default or alter legacy `PaperTradingEngine` / `VerifiedPaperRuntime` APIs.

## Security boundary and limitations

This makes gate requirement explicit and centrally validates configuration for the canonical real-time/paper runtime pair. It does not automatically wrap legacy APIs, prove all external callers choose strict mode, or replace schema, session, sequence-gap, or instrument validation. Explicitly gated wrappers from earlier phases remain available. Live trading remains on HOLD; no exchange order writes are performed. No NSE, Sensex, or forex adapter is certified by this work.

## Validation

The Phase 211 tests cover compatibility mode, missing/invalid threshold rejection under required mode, clock-provider validation, and propagation of strict policy to new runtimes. Existing Phase 205–210 targeted tests are also run individually where feasible. The full repository suite is not claimed as passing.
