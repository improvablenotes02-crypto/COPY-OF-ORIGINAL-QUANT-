# Phase 315 — Delta Snapshot to Account-Risk Reconciliation

## Integration

The new `reconcile_and_settle_pending_reservation()` orchestration path connects three existing boundaries:

1. A tenant/account-bound `DeltaReadOnlySession` obtains the complete read-only account snapshot and verifies the provider identity before and after collection.
2. The snapshot's independently timestamped order and fill histories are passed to `reconcile_delta_submission()`, which matches the exact client order ID, corroborates fills, checks completeness/freshness/skew, and refuses ambiguous or contradictory outcomes.
3. Only terminal states (filled, rejected, cancelled, expired) can produce settlement evidence. Open, partial, missing, incomplete, or contradictory observations leave the risk reservation pending.

The generated evidence is bound to the reservation/client-order ID, provider order ID, account scope, and SHA-256 hash of the complete account snapshot. The supplied reconciled state must decrement exactly one pending order and only that reservation's notional; other pending reservations cannot be released accidentally.

## Safety boundary

This path is read-only. It does not submit, retry, or cancel an order. It does not infer rejection from a timeout or from a missing order record. Account snapshots are sequential observations, not exchange-atomic; freshness and maximum skew remain enforced.

The caller still supplies the reconciled risk state, which must be derived from the same authenticated account snapshot by a trusted adapter. Synthetic tests do not prove live Delta connectivity, production KMS, or multi-node repository behavior. Live order writing remains disarmed.
