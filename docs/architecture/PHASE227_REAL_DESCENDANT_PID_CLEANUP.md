# Phase 227 — Real descendant PID cleanup regression

## Objective

Strengthen process-timeout auditing by verifying the real descendant PID is no longer executing after a timed-out test is terminated. The earlier POSIX regression only verified bounded completion while a child held the captured output pipe; this phase adds explicit PID-level verification.

## Implementation

- Added `tests/test_phase227_posix_descendant_pid_cleanup.py`.
- The test creates a temporary pytest file that starts a real sleeping child and records its PID, runs that file through the bounded audit runner with a timeout, then polls until the child is gone.
- On Linux, `/proc/<pid>/stat` state `Z` is treated as terminated because a zombie cannot execute; other platforms use `os.kill(pid, 0)` as the liveness probe.
- Added an Ubuntu CI job alongside the existing native Windows job. Both jobs verify the strict build manifest before executing platform-specific cleanup tests.

## Validation performed on this host

- Phase 222–225 plus Phase 227 targeted tests: **9 passed, 1 skipped**. The skipped test is the native Windows integration test, as this host is Linux.
- The new real-descendant PID cleanup test passed on this POSIX host.
- Snapshot guard reported no files added by tests and a pristine tree at test-session start.

## Limits

The Windows process-tree integration remains unverified until the Windows CI job executes successfully. The full repository test suite has not been certified. No strategy artifact, broker order path, risk threshold, or live-trading setting was changed; live trading remains on hold.
