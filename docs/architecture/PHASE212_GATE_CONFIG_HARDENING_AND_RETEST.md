# Phase 212 — Gate configuration hardening and reproducible retest

## Change

- Hardened `validate_paper_data_gate_config` to reject Python booleans as maximum-age values. In Python, `bool` is a subclass of `int`, so a naive float conversion silently interprets `True` as one second and `False` as zero seconds. These are not meaningful configuration values.
- Expanded the central policy regression test to cover both boolean values.
- Did not alter frozen strategy artifacts, pinned historical data, or digest values.

## Reproducible validation

The Phase 211 release record described frozen-file digest mismatches during some targeted test runs. Re-running the focused test files individually against the Phase 211 working tree in this session showed a pristine snapshot guard and successful exits; this phase does not reproduce that earlier failure. Results are recorded in the Phase 212 release record. No digest pins were changed to force a pass.

## Scope and limitations

- The gate remains opt-in for compatibility; this change does not make every legacy paper entrypoint fail closed by default.
- Targeted tests are not a substitute for a successful full repository suite.
- No exchange calls or order writes were made. Live trading remains on HOLD.
- Delta-focused integration remains the only concrete exchange focus; NSE, Sensex, and forex adapters are not certified.
