# Phase 316 — Settlement Evidence / Risk-State Hash Binding

## Contract

The durable reconciliation evidence now includes a canonical SHA-256 hash of the exact normalized `AccountRiskState` that is committed when a reservation settles.

Before the transaction begins, the repository validates the state and recomputes its canonical hash. Settlement is rejected unless the evidence hash matches the state hash. The same transaction writes the state, changes the reservation to `SETTLED`, and persists the evidence record.

## Benefit

This prevents evidence created for one risk-state payload from being accidentally reused to settle a different state. The state hash includes account scope, capital, P&L, positions, exposure, controls, and revision.

## Limit

A hash binds data identity; it does not prove that the state was honestly derived from an exchange snapshot. The Phase 315 adapter and production reconciliation worker remain responsible for deriving the state from authenticated, complete account observations. Live order writing remains disarmed.
