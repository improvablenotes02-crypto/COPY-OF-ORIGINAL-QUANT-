# Phase 261 — Durable order submission journal

## Change

Adds `SQLiteOrderSubmissionJournal`, a stdlib SQLite write-ahead reservation
store for client order IDs. Reservations are unique across executor instances
and process restarts. SQLite uses rollback-journal mode and FULL synchronous commits. The
journal stores a canonical payload SHA-256 digest rather than credentials or
the complete order payload.

Lifecycle: `PREPARED -> DISPATCHING -> ACKNOWLEDGED/FILLED/PARTIAL/
REJECTED/CANCELLED/EXPIRED/UNKNOWN -> RECONCILED`. A crash after PREPARED or
DISPATCHING leaves an unresolved record. UNKNOWN is deliberately unresolved.
Duplicate IDs are refused in every state, including terminal states, unless
an explicit reconciliation is recorded; reconciliation does not erase history
or permit reusing the same key.

## Operational requirements and limits

- Put the SQLite file on a persistent local filesystem with reliable SQLite
  locking. Do not use temporary storage or an unverified network filesystem.
- The runtime must reconcile every PREPARED, DISPATCHING, and UNKNOWN row with
  authoritative venue order history before any manual replacement order.
- A journal failure must block dispatch. Backups, retention, disk-full handling,
  filesystem durability, and multi-host coordination need deployment-specific
  verification.
- The executor integration is opt-in through explicit journal injection. Existing
  deployments that do not inject a journal are NOT thereby crash-safe. Wiring
  the journal into every live construction path and enforcing it as mandatory
  remains a release gate.
- This is local SQLite idempotency, not proof of venue-side idempotency. It does
  not guarantee exactly-once exchange execution, and it does not authorize live
  trading.

## Verification

The phase test covers restart persistence, ambiguous timeout retention,
concurrent unique reservation, payload minimization, and invalid transitions.
Overall QuantEngine remains `NOT_PRODUCTION_READY / HOLD`; live writes remain
disarmed.
