# QuantEngine Phase 223 — descendant timeout regression

## Goal

Close a concrete coverage gap in the bounded pytest audit runner: a timed-out
pytest process can spawn a descendant that ignores SIGTERM and inherits the
captured output pipe. The audit must not wait indefinitely for that pipe.

## Changes

- Added `tests/test_phase223_audit_descendant_cleanup.py`.
- The regression creates a temporary pytest module whose test starts a child
  Python process that ignores SIGTERM and sleeps while inheriting stdout/stderr.
- The bounded audit runner is expected to classify the run as `timeout` and
  return within six seconds.
- The test is POSIX-only because it specifically exercises POSIX signal
  semantics; it is skipped on Windows rather than claiming Windows coverage.
- No strategy, risk, exchange adapter, order-routing, or live-trading code was
  changed.

## Validation

Individual invocations completed successfully, with the snapshot guard pristine:

- `pytest tests/test_phase223_audit_descendant_cleanup.py -q`: 1 passed.
- `pytest tests/test_phase222_test_audit.py -q`: 4 passed.
- `pytest tests/test_async_refresh_10.py -q`: 8 passed.
- `pytest tests/test_phase216_strict_paper_preflight.py -q`: 9 passed.
- `pytest tests/test_phase218_preflight_deployment_smoke.py -q`: 1 passed.
- The bounded runner also ran `tests/test_async_refresh_10.py` in isolation:
  `PHASE222_BOUNDED_AUDIT_PASS`, 8 tests passed in about 10.6 seconds.
- Total targeted pytest tests: 23 passed across five invocations.

## Limitations

- The full repository suite has not been run to completion or certified green.
- Native Windows process-tree cleanup is not verified by the POSIX-only test.
- This is test infrastructure hardening only. It does not establish production
  exchange connectivity, strategy profitability, or production readiness.

## Safety posture

`is_production_ready = False`. Live trading remains on hold. No exchange order
writes were initiated by this phase.
