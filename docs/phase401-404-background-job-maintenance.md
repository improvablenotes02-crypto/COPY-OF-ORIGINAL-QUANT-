# Phases 401-404 — identity-bound backup verification and process safety
- **401:** Extend semantic queue integrity checks to the persisted principal snapshot: non-empty tenant/subject/session, canonical tenant list containing the row tenant, finite principal expiry and job expiry no later than principal expiry.
- **402:** Allow backup verification to bind an expected state-count mapping, rejecting malformed mappings and mismatched snapshots.
- **403:** Add a spawned independent-process race test proving only one process can publish a shared backup destination; the other receives no-clobber collision.
- **404:** Inject backup validation failure and assert temporary artifacts are removed and no destination is published.
No queue transitions, automatic replay, exactly-once claim, or live authorization are introduced. SQLite remains local single-host maintenance and production readiness remains false.
- **405:** Validate each job's principal snapshot from the same row, eliminating ambiguous timestamp-based identity lookups when jobs share timestamps.
- **406:** Validate all numeric timestamps and principal expiry before comparisons; malformed SQLite values fail closed without leaking a type error.
- **407:** Bind restore drills to expected queue-state counts at source verification and after isolated restore.
- **408:** Inject post-restore count-verification failure and assert no restore destination or private temporary artifact is left behind.

- **409:** Backup digests must be hexadecimal SHA-256 values; verification opens the SQLite artifact read-only and cannot write through the verification connection.
- **410:** Keep backup verification non-mutating by enforcing SQLite query-only mode and read-only URI access.
- **411:** Add a bounded owner-only inventory report with verified, rejected, candidate and truncation counts; retain the tuple API as a compatibility wrapper.
- **412:** Extend the maintenance health summary with bounded inventory metrics while preserving explicit replay-disabled and production-not-ready indicators.
