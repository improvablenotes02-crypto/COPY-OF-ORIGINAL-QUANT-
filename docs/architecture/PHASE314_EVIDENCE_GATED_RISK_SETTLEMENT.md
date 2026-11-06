# Phase 314 — Evidence-Gated Account Risk Settlement

## Contract

Durable reservation settlement requires an immutable AccountRiskReconciliationEvidence record bound to the exact account scope and reservation ID. It records the authenticated-read source designation, exact client and provider order identities, terminal order status, UTC observation time, snapshot SHA-256, verified identity, and complete order/fill/position observations.

The evidence is stored in the same repository transaction that updates account-risk state and marks the reservation settled. Retrieval is scope checked and survives repository restart.

## Phase 317 safety refinement

The persistence boundary now permits settlement only for an exchange-rejected order. The committed state must be the exact current state with only this reservation's pending-order count and pending notional removed. Equity, P&L, exposure, position count, risk basis, kill switch, and trading-enabled controls must remain unchanged.

A hash binds the state payload but does not prove that it was derived from an exchange observation. This narrow rule prevents a caller from smuggling unverified risk-state changes through an otherwise valid evidence envelope.

## Deferred outcomes

Filled, partially filled then cancelled, cancelled, and expired orders remain pending until a separately implemented position-reconciliation projection can derive their effects safely. Ambiguous or incomplete observations also remain pending. Live order writing remains disarmed.
