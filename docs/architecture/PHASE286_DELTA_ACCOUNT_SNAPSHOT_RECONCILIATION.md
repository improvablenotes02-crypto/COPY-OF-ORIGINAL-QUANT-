# Phase 286 — Read-only Delta account snapshot and completeness

Status: implementation and offline tests committed. No live account was
contacted; no real balances, positions, orders or fills were fetched.

## Snapshot contract

`DeltaReadOnlySession.get_account_snapshot(max_pages=100)` assembles:
- authenticated Delta provider identity;
- balances;
- positions;
- fully paginated active and historical orders;
- fully paginated fills;
- tenant/internal account scope, venue region and environment;
- component observation timestamps and cursor-exhaustion evidence.

Collection is fail-closed:
- the provider identity must already be bound to the internal account;
- identity is checked before and after collection;
- balances and positions must return successful API envelopes;
- order and fill snapshots must be complete and have valid result lists;
- both active and historical order cursors and the fills cursor must be
  explicitly exhausted;
- order/fill provider account IDs must match the bound identity;
- any failure refuses the aggregate result instead of returning a
  misleading partial snapshot.

## Consistency model

This is **not an exchange-atomic snapshot**. Balances, positions, orders and
fills are separate endpoint observations made at different moments. The
response preserves order/fill observation timestamps and states
`observation_is_exchange_atomic = false`. Reconciliation logic must account
for concurrent fills, order transitions and position updates between calls.
A later phase will add bounded re-reads and consistency windows; no claim of
exactly-once exchange execution is made here.

## Security boundaries

- All reads are performed through the account's tenant-scoped read-only
  session and region-pinned host.
- No order placement, cancellation, amendment, transfer or withdrawal API is
  exposed by the facade.
- The registry still requires a production KMS provider and trusted
  authenticated tenant principal before real multi-user credential onboarding.
- Real account API keys must be created with minimum read-only permissions
  and configured locally in the chosen secret-management integration.

## Validation

Offline tests cover successful collection, unbound identity refusal,
unsuccessful balance/position envelopes, incomplete order/fill histories,
unexhausted cursors, provider-account mismatches and identity changes during
collection. Fake transports are used; no exchange network traffic is made.
