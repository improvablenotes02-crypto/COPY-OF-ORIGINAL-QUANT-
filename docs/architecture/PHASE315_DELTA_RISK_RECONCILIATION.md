# Phase 315 — Delta Snapshot to Account-Risk Reconciliation

## Integration

The reconcile_and_settle_pending_reservation path connects three boundaries:

1. A tenant/account-bound DeltaReadOnlySession obtains a complete read-only account snapshot and verifies provider identity before and after collection.
2. Independently timestamped order and fill histories are passed to reconcile_delta_submission, which matches the exact client order ID, corroborates fills, checks completeness/freshness/skew, and refuses ambiguous or contradictory outcomes.
3. The current supported settlement path accepts only an exchange-rejected order with no contradictory fill evidence. It releases exactly one pending reservation and preserves every other risk-state field.

## Fail-closed terminal handling

Filled, partially filled, cancelled, and expired orders are deliberately left pending. The repository does not yet have a trusted projection that derives exposure, position count, equity, and P&L from the same authenticated account observations. Until that projection exists, releasing pending notional for an executed order could understate risk.

The orchestration returns before transitioning the submission journal for those terminal states, so the durable journal and risk reservation are not falsely presented as reconciled. The caller-supplied state must equal the exact projection from the current persisted state that decrements only the target reservation's pending count and notional. The repository independently enforces the same invariant inside its transaction.

## Safety boundary

This path is read-only. It does not submit, retry, or cancel an order. It does not infer rejection from a timeout or missing order record. Account snapshots are sequential observations, not exchange-atomic; freshness and maximum skew remain enforced.

Synthetic tests do not prove live Delta connectivity, production KMS, or multi-node repository behavior. Live order writing remains disarmed.
