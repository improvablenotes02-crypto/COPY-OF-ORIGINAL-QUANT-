# Phase 275 — Abrupt Process-Exit Recovery Certification

## Objective

Verify that committed submission-journal lifecycle records survive abrupt
process termination and that a fresh process cannot reuse an already
reserved client order ID.

## Failure boundary

A worker process commits a journal state and then terminates via
`os._exit(73)`, deliberately bypassing Python cleanup handlers. The parent
process opens a new journal instance and checks the persisted state.

The deterministic checkpoints are:

- PREPARED committed, before any dispatch transition.
- DISPATCHING committed, before a transport outcome is known.
- UNKNOWN committed, representing an ambiguous transport outcome.
- ACKNOWLEDGED committed, representing a durable acknowledgement recorded
  before the executor returns to its caller.

## Required invariants

- Committed state survives abrupt process exit and a new journal instance.
- PREPARED, DISPATCHING, and UNKNOWN remain visible as unresolved.
- ACKNOWLEDGED remains persisted as ACKNOWLEDGED, not reclassified.
- The same client order ID cannot be reserved again after restart, regardless
  of its persisted lifecycle state.
- Recovery performs no broker/venue I/O and never dispatches or resubmits an
  order automatically.

## Test strategy

The test uses isolated temporary SQLite files and child Python processes.
Each worker reaches one committed lifecycle checkpoint, then exits with
`os._exit`. The parent verifies the exit checkpoint, reopens the database,
checks state and unresolved inventory, and attempts a duplicate reservation.
Each child has a bounded 15-second completion timeout; cleanup kills a worker
if it exceeds that bound.

## Scope and limitations

This certifies process-crash behavior after successful SQLite commits on the
CI runner's local filesystem. It does not simulate power loss, kernel panic,
storage-controller cache loss, filesystem corruption, or termination in the
middle of SQLite's commit protocol. It does not prove exchange-side acceptance
or exactly-once network delivery. DISPATCHING and UNKNOWN must still be
reconciled against authoritative venue evidence before any further action.

No broker credentials, network calls, live orders, or live-execution
authorization are used or changed by this phase. Live order writing remains
disarmed.

## Validation

```bash
python -m pytest tests/test_submission_journal_phase275.py -q
python scripts/generate_manifest.py --root . --verify --strict
```
