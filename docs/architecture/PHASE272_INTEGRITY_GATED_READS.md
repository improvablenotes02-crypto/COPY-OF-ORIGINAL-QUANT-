# Phase 272 — Integrity-gated journal reads

## Change

`SQLiteOrderSubmissionJournal.get()` and `.unresolved()` now acquire the journal lock, begin a SQLite `IMMEDIATE` transaction, run the full schema/page/record integrity validator, read their requested rows from that same transaction, and commit. Any integrity or database error rolls back and propagates; no partial snapshot is returned.

## Why it matters

The live broker engine uses unresolved submission records as a routing safety check. Previously, read methods queried SQLite directly without the integrity certification already required for writes. Corrupt or unsupported journal content could therefore be observed by a safety-critical read path without the same fail-closed guarantees.

## Trade-off

Reads now serialize against writers while validation runs and may increase latency for large journals. This is deliberate fail-closed behavior; a future indexed/attested integrity strategy must preserve equivalent guarantees before relaxing it.

## Scope

No order submission, broker connectivity, automatic reconciliation, retry, or live-execution enablement is added.

## Verification

    python -m pytest tests/test_submission_journal_phase272.py tests/test_submission_journal_phase261.py tests/test_submission_journal_phase267.py tests/test_submission_journal_phase268.py tests/test_submission_journal_phase269.py tests/test_submission_journal_phase270.py tests/test_submission_journal_phase271.py -q
    python scripts/generate_manifest.py --root . --verify --strict
