# QuantEngine Phase 224 — Cross-platform audit cleanup checks

## Scope

This phase adds unit tests for the bounded audit runner's Windows cleanup branch.
It verifies that the runner asks Windows `taskkill` to terminate the process tree
(`/T /F`), bounds that command with a timeout, and falls back to direct process
termination if `taskkill` is unavailable or times out.

## Validation boundary

The Windows-specific primitives are mocked in this test environment. These tests
verify command selection and fallback behavior, but **do not prove native Windows
process-tree cleanup**. The POSIX descendant-held-pipe integration regression from
Phase 223 remains the only end-to-end descendant cleanup test and is skipped on
Windows.

## Safety and project scope

- Only test-runner infrastructure and tests/documentation changed.
- No strategy, broker adapter, exchange credentials, order-routing, or live-trading
  behavior was changed.
- The legacy `main.py` and frozen strategy artifacts remain unchanged.
- Full repository tests remain uncertified.

## Windows verification command

On a native Windows host, run:

```powershell
python -m pytest tests/test_phase224_windows_process_cleanup.py -q
python -m pytest tests/test_phase223_audit_descendant_cleanup.py -q
```

The Phase 223 test is expected to skip on Windows because it specifically tests
POSIX signal semantics. Native Windows descendant cleanup still requires a
separate Windows-only integration test using a real spawned child process.
