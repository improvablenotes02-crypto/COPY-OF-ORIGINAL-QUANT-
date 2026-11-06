# Phase 316 — Settlement Evidence / Risk-State Hash Binding

## Contract

Reconciliation evidence includes a canonical SHA-256 hash of the exact normalized AccountRiskState committed when a reservation settles. Before the transaction, the repository recomputes the canonical hash and rejects evidence that binds a different state. The transaction writes the state, changes the reservation to SETTLED, and persists the evidence record atomically.

## Phase 317 refinement

The hash check is necessary but not sufficient. The repository now also enforces a narrow rejected-order projection: only the target pending reservation may be removed; every other risk-state field must remain unchanged at the typed-value level. Executed or cancelled orders cannot settle until a trusted position-reconciliation projection exists.

## Limit

A hash binds data identity; it does not prove that the state was honestly derived from an exchange snapshot. The Phase 315 adapter and future position-reconciliation worker remain responsible for deriving state from authenticated, complete account observations. Live order writing remains disarmed.
