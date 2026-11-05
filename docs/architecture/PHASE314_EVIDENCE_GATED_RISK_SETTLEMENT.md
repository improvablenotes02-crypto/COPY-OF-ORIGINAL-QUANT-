# Phase 314 — Evidence-Gated Account Risk Settlement

## Risk

A durable reservation should not be marked settled merely because a caller supplies a state object. That would allow a programming error or an unverified response to release pending risk capacity without an auditable exchange reconciliation record.

## Contract

Settlement now requires an immutable `AccountRiskReconciliationEvidence` record bound to the exact account scope and reservation ID. It requires:

- Delta authenticated-read source designation;
- provider exchange order ID and terminal order status;
- UTC-aware observation time;
- SHA-256 snapshot identity;
- verified account identity;
- complete order, fill, and position observations;
- confirmation that the order is no longer open.

The evidence is written in the same SQLite transaction that updates the account-risk state and marks the reservation settled. The repository exposes a scope-checked retrieval method so evidence remains available after restart.

## Safety boundary

This is a typed application contract, not cryptographic proof that a caller really authenticated with Delta. The production Delta reconciliation adapter must construct evidence only after signature verification, account identity re-check, pagination exhaustion, and consistency checks. Unit tests use synthetic evidence and do not certify a live exchange integration.

An ambiguous or incomplete observation must leave the reservation pending. Live order writing remains disarmed.
