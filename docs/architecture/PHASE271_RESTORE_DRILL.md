# Phase 271 — Offline submission-journal restore drill

## Scope

The new core.execution.backup_restore_drill.run_backup_restore_drill function restores a supplied backup into a disposable temporary directory, validates the restored SQLite database, and compares every persisted submission row with the source backup. The temporary copy is removed automatically after the drill.

## Safety properties

- Requires a caller-supplied SHA-256 digest and verifies it before restoring.
- Source backup is read-only during the drill.
- No broker/network calls, venue reconciliation, order submission, retry, or live-execution authorization.
- Compares all persisted columns for every client order ID, not just aggregate counts.
- Reports unresolved rows and state counts so UNKNOWN/PREPARED records remain visible.

A PASS means only that this backup was locally restorable and row-identical at drill time. It is not a proof of independent hash authenticity, disaster-site availability, broker correctness, or production readiness.

## Verification

    python -m pytest tests/test_submission_journal_phase271.py -q
    python scripts/generate_manifest.py --root . --verify --strict
