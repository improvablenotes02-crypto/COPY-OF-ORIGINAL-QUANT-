# Phase 262 — Production journal enforcement and recovery halt

## Changes

- Fixed SQLite connection lifecycle: transaction methods now explicitly close
  each connection after commit/rollback. This addresses Windows file-handle
  retention observed in the Phase 261 certification job.
- Live safety tokens now distinguish explicitly test-only arming from
  production settings-based arming. The test-only marker has a separate
  process-local mint; changing the marker on a token invalidates it.
- A production-minted LIVE order submission is refused unless a durable
  submission journal is injected. This applies at the Delta order-executor
  boundary, before exchange transport.
- BrokerEngine also refuses to start with the production Delta executor when
  its durable journal is missing.
- Before every live route, BrokerEngine checks the journal. Unresolved
  PREPARED, DISPATCHING, or UNKNOWN records halt new routing and require
  authoritative venue reconciliation. Journal read errors also halt routing.
  Clearing the broker reconciliation halt alone does not clear journal rows.

## Safety and scope

The test-only token remains available for offline fake-transport tests. It is
not production authorization. Production journal injection must use a
persistent local path with tested backup and filesystem behavior. The journal
does not query venue history itself; unresolved records must be reconciled
against authoritative venue data before explicit resolution.

This phase does not enable live trading or claim exactly-once execution.
Live writes remain disarmed by default. Full project release remains
`NOT_PRODUCTION_READY / HOLD`.

## Validation

The CI workflow now includes the Phase 262 production-token and executor
journal-required tests, the existing submission-journal tests, and the
existing runtime data-gate suite on Ubuntu and Windows.
