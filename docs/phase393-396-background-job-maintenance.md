# Phases 393–396 — background-job database integrity and recovery

- 393: owner-only read-only SQLite quick-check, required schema/index verification, and queue-state counts.
- 394: SQLite online backup to a same-directory temporary file, integrity verification, fsync, and atomic no-clobber publication.
- 395: SHA-256 and SQLite/schema verification of backup artifacts; reject tampered and structurally invalid files.
- 396: isolated no-clobber restore drill followed by digest and SQLite/schema verification.

These controls apply only to the single-host SQLite job queue. Backup and restore do not change queue state, establish external broker outcomes, or authorize job replay. Production readiness remains false; live execution remains disarmed.
