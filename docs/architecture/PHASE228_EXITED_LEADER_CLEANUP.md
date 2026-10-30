# Phase 228 — Descendant cleanup after audit leader exit

## Objective

Cover the process-tree edge case where the timed-out pytest leader exits before the audit timeout, but a descendant inherits the captured output pipe and keeps `communicate()` blocked.

## Implementation

- Added `tests/test_phase228_posix_exited_leader_cleanup.py`.
- The fixture starts a real sleeping child, then lets the pytest process exit immediately. The test requires `_run_one` to classify the run as a timeout and verifies that the descendant PID is no longer executing.
- The `/proc/<pid>/stat` probe parses the state field after the final closing parenthesis, because the process `comm` field may contain spaces; Linux zombies are treated as terminated because they cannot execute.
- Added the new regression to the Ubuntu CI job alongside the Phase 227 PID-level and Phase 223 pipe-inheritance tests.

## Validation boundary

This is a focused POSIX regression, not proof of native Windows cleanup. The Windows integration must pass on a Windows runner; this Linux environment cannot certify that result. The full repository suite remains uncertified unless explicitly run to completion. No trading strategy artifacts, broker order paths, risk thresholds, or live-trading settings are changed.
