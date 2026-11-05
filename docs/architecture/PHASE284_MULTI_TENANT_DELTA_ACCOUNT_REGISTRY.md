# Phase 284 — Tenant-scoped Delta account registry

Status: implementation scaffold and offline regression tests committed;
**production credential onboarding remains blocked** pending a selected
KMS/encryption provider and authenticated tenant identity integration.

## Scope delivered

- A tenant-scoped Delta account registry accepts an opaque tenant principal,
  account label, region, environment, API key and API secret.
- Region/environment must be one of the four explicit supported combinations.
- Credentials are serialized only in memory, encrypted through an injected
  `EncryptionProvider`, and persisted as ciphertext plus key/algorithm metadata.
- Authenticated encryption receives associated data binding ciphertext to
  tenant ID, internal account ID, venue, region and environment. Moving a
  ciphertext row to another tenant or venue scope must fail decryption.
- SQLite repository stores ciphertext only and scopes reads, lists and deletes
  by both tenant ID and account ID.
- Metadata listing never returns API keys or secrets.
- The read-only session facade exposes balance, positions, identity and
  history reads; it intentionally has no order placement or cancellation API.
- The facade binds its REST host from the stored region/environment pair.

## Important boundaries

1. **No production encryption provider is shipped in this phase.** The
   interface requires authenticated encryption and context binding. A test
   provider exists only in tests and is explicitly insecure. Production must
   inject an approved KMS-backed implementation; do not replace it with a
   static application key or plain environment variable.
2. SQLite is a local/single-process development repository, not a distributed
   production tenant database. Production must inject a durable shared
   repository with migrations, backup/restore, access controls and concurrency
   guarantees.
3. The registry does not authenticate users. Its `tenant_id` must come from
   trusted server-side authentication/session middleware, never from an
   untrusted request field. That identity integration is not yet implemented.
4. The registry does not silently bind a provider account identity. Phase 285
   will authenticate read-only and bind the Delta-reported user ID after an
   explicit, verified connection.
5. The read-only facade is an application boundary, not a Python sandbox.
   The underlying exchange object is private by convention. Never serialize
   the session, log it, or expose it to untrusted plugins.
6. No live write authority is added. `ALLOW_LIVE` and `LIVE_EXECUTE` remain
   disabled by default; no order write is performed by this registry.

## API contract

- `DeltaAccountRegistry(repository, encryption_provider)`
- `register_account(tenant_id, label, region, environment, api_key, api_secret)`
- `list_accounts(tenant_id)`
- `delete_account(tenant_id, account_id)`
- `open_read_only_session(tenant_id, account_id)`

The encryption provider contract is:
- `encrypt(plaintext, associated_data) -> CiphertextEnvelope`
- `decrypt(envelope, associated_data) -> plaintext`

The provider must authenticate associated data, reject tampering, protect
key material outside the application database, support key rotation, and
provide auditable key identifiers. The registry does not log plaintext or
include ciphertext in object representations.

## Production blockers / next phases

- Select the KMS provider and deployment environment; then implement its
  adapter and rotation/revocation controls.
- Integrate authenticated tenant identity and authorization policy.
- Replace the local SQLite repository with the chosen shared production
  database implementation.
- Phase 285: connect each account read-only, verify Delta-reported user ID,
  and persist the provider identity as a one-way account binding.
- Phase 286: per-account balances, positions, orders, fills and reconciliation.
- Phase 287: per-account risk and execution authorization isolation.

Until these are complete, the multi-account feature is an offline-tested
foundation, not a production-ready credential onboarding service.
