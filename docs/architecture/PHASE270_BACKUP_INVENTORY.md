# Phase 270 — Read-only submission-journal backup inventory

## Scope

Phase 270 adds core.execution.backup_inventory.verify_backup_inventory. It inspects caller-supplied backup paths and returns a JSON-serializable report. It does not discover backups automatically, change files, enforce retention, restore journals, or submit/retry orders.

## Checks and statuses

- VALID: SQLite integrity/schema/record validation passed and any supplied expected SHA-256 matched. Without an expected digest, the hash is marked unanchored; a locally computed digest is not proof of authenticity.
- HASH_MISMATCH: the supplied expected digest did not match the file.
- MISSING: the path is missing or not a regular file.
- INVALID: file access, stable-snapshot, digest-format, or SQLite validation failed.

The report includes file size, modification timestamp, age relative to an injectable reference clock, schema version, total rows, unresolved rows, and aggregate counts. Paths are sorted for deterministic report ordering.

## Operational limits

A backup can be structurally valid but stale, incomplete as an operational recovery set, or maliciously replaced along with its locally stored hash. Store expected digests in a separately protected location for meaningful tamper detection. A valid backup with unresolved submissions still requires venue reconciliation before any execution decision. No retention period or automatic deletion is defined by this phase.

## Verification

Run:

    python -m pytest tests/test_submission_journal_phase268.py tests/test_submission_journal_phase269.py tests/test_submission_journal_phase270.py -q
    python scripts/generate_manifest.py --root . --verify --strict
