# Phase 285 — Delta read-only identity binding

Status: implementation and offline contract tests committed. No real
credentials were loaded and no live Delta account was contacted.

## Behaviour

- The account registry opens a narrow read-only session using the stored
  tenant-scoped encrypted credentials and the account's pinned region and
  environment.
- `verify_and_bind_identity` calls the authenticated
  `GET /v2/users/trading_preferences` identity path through the existing
  Delta adapter.
- The provider-reported user ID must be a positive decimal identifier.
- The first successful verification binds that ID to the internal account
  record. A repeated verification is idempotent only when the ID is equal.
- A different provider ID cannot overwrite an existing binding.
- Order and fill history snapshots are checked against the stored provider
  identity when one has been bound.
- The repository binding update is conditional and tenant-scoped. A
  different tenant cannot bind, inspect, or replace the account identity.
- The read-only session still exposes no order placement or cancellation
  methods.

## External verification still required

The tests use a fake encryption provider and fake Delta transport. They prove
the local identity-binding contract, not that a real API key authenticates.
A real account must later be configured locally with a read-only-restricted
API key for the correct region/environment. Never paste API keys or secrets
into ChatGPT, commits, issue comments, or CI logs.

The first real-account probe must be read-only and verify:
1. API key/secret authentication succeeds at the matching regional host.
2. Delta returns a valid authenticated `user_id`.
3. The observed ID matches the intended account owner.
4. The key has only the minimum read permissions needed.
5. No order, cancel, amend, transfer or withdrawal request is emitted.

An India Demo key must use the India Demo host and India Demo credential slot;
an India Production key must use the India Production host and Production
credential slot. Global keys remain separate.

## Status

- Offline account identity binding: implemented and regression-tested.
- Real-account authentication: NOT YET VERIFIED.
- Multi-user production credential storage: BLOCKED pending KMS provider.
- Authenticated tenant middleware and shared production repository: NOT YET
  IMPLEMENTED.
- Live order writing: DISARMED.
