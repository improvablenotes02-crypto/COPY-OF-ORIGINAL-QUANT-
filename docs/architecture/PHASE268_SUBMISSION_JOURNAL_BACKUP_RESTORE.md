Phase 268 — Submission journal backup and restore

SQLiteOrderSubmissionJournal.backup_to(destination) uses SQLite's online backup API to produce a standalone, transactionally consistent database snapshot. The snapshot is fsynced, checked with SQLite integrity_check plus the supported schema and record validator, counted for total and unresolved submissions, SHA-256 fingerprinted, and atomically published. Existing destinations are not overwritten unless overwrite=True is explicitly supplied.

SQLiteOrderSubmissionJournal.restore_from(backup, destination) validates the source before copying, optionally verifies an expected SHA-256, copies to a temporary file beside the destination, fsyncs and validates that copy, then atomically installs it. It refuses an existing destination unless overwrite=True. A restored unresolved PREPARED, DISPATCHING, or UNKNOWN record remains unresolved and continues to block reuse of its client order ID.

The SHA-256 fingerprint detects accidental or untrusted transfer changes only when the expected value is obtained through a trusted channel. It is not a digital signature or proof against an attacker who can replace both the backup and its expected digest. Backups must be stored separately from the live journal and protected with appropriate filesystem permissions. Restore does not itself authorize resubmission; venue reconciliation remains mandatory.

Live order writing remains disarmed by existing project controls.
