# Phase 310 — Atomic Idempotent Account Risk Reservations

## Contract

The persistent risk repository now supports atomic order-risk reservation, release, and settlement operations.

- `reserve_order()` evaluates the proposal and increments pending order count/exposure in the same SQLite write transaction.
- A globally unique reservation ID binds to the exact account scope and proposal. Repeating the same request is idempotent; reusing the ID for a different proposal is rejected.
- `release_reservation()` removes pending exposure once, for an order confirmed not submitted, rejected, or cancelled.
- `settle_reservation()` replaces the pending reservation state with a caller-supplied authoritative reconciled account snapshot and marks the reservation settled.
- Exposure and pending-order limits are re-evaluated under the transaction, so simultaneous proposals cannot both consume the same remaining headroom.

## Ambiguous order outcomes

A reservation must remain pending when order submission has an ambiguous transport outcome. Do not release it merely because a client timed out. Keep the risk capacity locked until authenticated exchange reconciliation determines whether the order exists and the caller supplies a reconciled state or confirmed cancellation/rejection.

## Deployment boundary

This is a risk preflight/reservation primitive, not an order executor. It does not submit orders, create live-write permits, or enable live trading. SQLite remains a local/single-node adapter; production must use a shared transactional repository implementing equivalent atomic reservation semantics.

## Verification

Tests cover atomic pending exposure updates, idempotent reservation IDs, conflicting ID reuse, one-time release, authoritative settlement, ambiguous-outcome lock retention, and account exposure limit enforcement.
