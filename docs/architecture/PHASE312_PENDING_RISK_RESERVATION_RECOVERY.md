# Phase 312 — Durable Pending Risk Reservation Recovery

## Purpose

A process restart must not erase unresolved order-risk reservations. If an order submission has an ambiguous transport outcome, the reservation remains pending and continues consuming the account's pending-order and exposure budget until authenticated exchange reconciliation determines the outcome.

## Recovery API

- `PersistentAccountRiskCoordinator.list_pending_reservations(scope)` exposes pending reservations for one tenant/account scope.
- The SQLite adapter returns reservations in deterministic creation-revision and reservation-ID order.
- Returned records include reservation ID, account scope, notional, status, and creation revision.
- Released and settled reservations are excluded.
- An unregistered account returns an empty tuple.

## Operational sequence

1. On startup, load pending reservations for each configured account scope.
2. Reconcile each reservation against authenticated exchange order/fill/position history.
3. Keep unresolved or ambiguous outcomes pending. Do not infer rejection from a timeout.
4. Release only after authoritative evidence that no live order remains (or a confirmed rejection/cancellation).
5. Settle only with an authoritative reconciled account-risk state and the current expected revision.
6. Record the reconciliation evidence and outcome in the surrounding execution journal.

## Limits

This API exposes durable recovery state; it does not itself query Delta, infer order outcomes, submit/cancel orders, or authorize live trading. SQLite remains a local/single-node adapter. Production multi-node deployments require a shared transactional repository and an independently certified reconciliation worker. Live order writing remains disarmed.
