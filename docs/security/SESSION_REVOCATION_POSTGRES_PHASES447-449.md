# Phases 447-449 — PostgreSQL session revocation

Phase 447 adds a shared PostgreSQL denylist keyed by the IdP-global subject/session pair. Parameterized SQL and an atomic upsert make revocation idempotent under concurrent writers. The earliest revocation timestamp is retained. Read/write errors are redacted and propagate to the existing fail-closed validator.

Phase 448 adds migration 003 for the central identity database plus tests for restart persistence, global session scope, concurrent writers, invalid values, and error redaction.

Phase 449 defines deployment admission: the adapter deliberately remains production_ready=false until a dedicated service role, restricted grants, HA/backup recovery, and IdP session semantics are independently certified. Apply the migration only to the central identity database; tenant clients must not receive access.

Limitations: owner removal does not yet enumerate the removed member's active IdP sessions or invoke remote IdP logout. The existing coordinator revokes only a verified principal supplied by trusted server code. No live trading behavior is changed.
