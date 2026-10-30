# Phase 226 — Native Windows process-tree CI gate

## Objective

Make the Phase 225 real-descendant timeout-cleanup test execute on a native Windows runner rather than being silently skipped on Linux. The workflow is deliberately narrow: it tests the existing `taskkill /T /F` cleanup path and nearby audit regressions; it does not change strategy artifacts or enable live orders.

## Implementation

Added `.github/workflows/windows-process-tree.yml` with `windows-latest`, Python 3.12, pinned pytest 9.0.3, a strict package-manifest verification step, the native Windows descendant test, and the Phase 222–224 cleanup regression tests. It runs on pushes, pull requests, and manual dispatch. Repository permissions are read-only and checkout credentials are not persisted.

## Local validation scope

The development host for this phase is not Windows. Therefore the native Windows test cannot be executed locally, and no Windows CI result is claimed by this report. The workflow definition and test collection can be checked locally, but proof that Windows terminates the real child process requires the workflow to run on GitHub's Windows runner.

## Acceptance criteria

1. Strict manifest verification succeeds on the checked-out tree.
2. The native Windows test runs (not skips) on `windows-latest` and passes.
3. Phase 222–224 cleanup regressions pass on Windows.
4. Any failure is retained as a CI failure; the workflow must not use `continue-on-error` or convert a skip into success.

## Safety boundary

No trading strategy, broker adapter, order path, risk threshold, or live-trading switch was modified. This is a test-infrastructure improvement only. It does not certify the full repository test suite or production/live-trading readiness.
