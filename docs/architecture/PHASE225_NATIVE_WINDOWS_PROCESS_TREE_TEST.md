# Phase 225 — Native Windows process-tree integration test

## Change

Added `tests/test_phase225_native_windows_process_tree.py`. On Windows, this
integration test creates a temporary pytest module that starts a real Python
descendant process, writes its PID to a marker, and then hangs. It invokes the
same bounded audit runner used by the deployment audit, expects a timeout
classification, and checks that the descendant PID is no longer running.

The test is marked to skip on non-Windows hosts because mocked `taskkill`
checks cannot prove native Windows process-tree semantics.

## Validation in this build environment

- `tests/test_phase225_native_windows_process_tree.py`: **1 skipped**, expected
  on this non-Windows host. Native Windows behavior is not claimed as tested.
- `tests/test_phase224_windows_process_cleanup.py`,
  `tests/test_phase222_test_audit.py`, and
  `tests/test_phase223_audit_descendant_cleanup.py`: **8 passed** in one
  targeted run; snapshot guard was pristine.
- The POSIX descendant-held-pipe regression is exercised on this host through
  the Phase 223 test.

## Windows validation command

Run from the extracted project root on a native Windows machine:

```powershell
python -m pytest tests/test_phase225_native_windows_process_tree.py -q
```

A Windows run must show the test passing, not skipped, before claiming native
process-tree cleanup is verified. If it fails, retain the failure output and
investigate the runner's timeout/cleanup behavior; do not weaken the assertion.

## Scope

No strategy, exchange adapter, order-routing, or live-trading behavior changed.
The full repository suite remains uncertified. This test adds a native check but
does not itself execute on Windows in the current build environment.
