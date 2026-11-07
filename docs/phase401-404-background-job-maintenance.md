# Phases 401-404 — identity-bound backup verification and process safety
- **401:** Extend semantic queue integrity checks to the persisted principal snapshot: non-empty tenant/subject/session, canonical tenant list containing the row tenant, finite principal expiry and job expiry no later than principal expiry.
- **402:** Allow backup verification to bind an expected state-count mapping, rejecting malformed mappings and mismatched snapshots.
- **403:** Add a spawned independent-process race test proving only one process can publish a shared backup destination; the other receives no-clobber collision.
- **404:** Inject backup validation failure and assert temporary artifacts are removed and no destination is published.
No queue transitions, automatic replay, exactly-once claim, or live authorization are introduced. SQLite remains local single-host maintenance and production readiness remains false.
