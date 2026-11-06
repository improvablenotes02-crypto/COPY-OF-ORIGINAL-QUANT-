# Phase 273 — Integrity-Gated Journal Health Report

## Scope

Adds `SQLiteOrderSubmissionJournal.health_report()`, a read-only operational
snapshot for local diagnostics and deployment health checks.

The method acquires the journal lock, opens a deferred SQLite read transaction,
validates the complete database/schema/record set, and computes total and
per-state counts from the same transaction. It reports unresolved submissions
as the sum of PREPARED, DISPATCHING, and UNKNOWN records.

## Safety properties

- Corrupt pages, unsupported schema, invalid records, or database errors fail
  closed with the journal validation error.
- No rows are inserted, updated, deleted, reconciled, or resubmitted.
- No broker or venue network calls occur.
- `live_execution_authorized` is always false; this report is not an execution
  authorization or a substitute for the live safety gate.
- The snapshot is consistent at transaction time. `generated_at_ns` records
  report construction time, not venue time.

## Returned fields

`integrity_valid`, `schema_version`, `record_count`,
`unresolved_count`, `state_counts`, `live_execution_authorized`, and
`generated_at_ns`.

## Validation

Run:

```bash
python -m pytest tests/test_submission_journal_phase273.py -q
python scripts/generate_manifest.py --root . --verify --strict
```

The tests cover state aggregation, read-only behavior, the explicit
non-authorization flag, and fail-closed handling of corruption in an unrelated
record.
