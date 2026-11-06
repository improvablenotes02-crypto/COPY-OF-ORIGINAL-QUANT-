# Delta credential lifecycle and production boundary — Phase 351

## Scope

This document describes the credential lifecycle implemented by the Delta account registry. It does not certify the registry or the wider QuantEngine as production-ready. The included SQLite repository remains a local-development/test adapter and declares `production_ready = False`.

## Credential registration

1. Validate tenant, account label, Delta region, environment, API key, and API secret.
2. Serialize the API key and secret only in memory.
3. Encrypt the payload with the injected encryption provider and account-scoped associated data.
4. Persist the ciphertext envelope (`key_id`, `algorithm`, ciphertext) and metadata.
5. Do not return plaintext credentials from account metadata or list operations.

The test encryption providers are deterministic test doubles. They are not suitable for production and must never be used to store real credentials.

## API credential rotation

1. Read the current tenant-scoped account record and its credential generation/version.
2. Construct a temporary read-only Delta client using the replacement key and secret.
3. Authenticate against Delta's authenticated-user identity endpoint and validate the returned numeric user ID.
4. If the account is already bound, require the replacement credentials to resolve to the same Delta user ID. If unbound, bind the verified ID as part of the successful atomic update.
5. Close the temporary client on every outcome.
6. Encrypt the replacement payload.
7. Compare-and-swap the account using both the expected credential generation and expected account update timestamp.
8. In one repository transaction, update the ciphertext envelope, increment the credential generation, and append the rotation audit event.
9. If another writer changed the record, return a conflict. Do not automatically retry or overwrite the newer record.

Successful rotation invalidates sessions created from the previous account record. A failed authentication, identity mismatch, encryption error, audit-write failure, or compare-and-swap conflict must not replace the stored credentials.

## Encryption-key rewrapping

Rewrapping is different from changing a Delta API key:

- Decrypt the existing credential payload using the old envelope key identifier.
- Encrypt the same payload using the provider's active key.
- Require the provider to return a different immutable key identifier.
- Commit the new envelope, increment the credential generation, and append an audit event atomically.
- Do not call Delta or change the API key/secret during a pure encryption-key rewrap.

This operation supports controlled KMS key-version transitions. A deployment must retain access to old key versions for decryption until all records have been successfully rewrapped and recovery obligations are met.

## Audit evidence

The local repository writes account changes and rotation audit events in the same SQLite transaction. Audit events are append-only through database triggers and include tenant/account scope, old/new generation, old/new key IDs, event time, and a per-account SHA-256 hash chain.

The hash chain detects accidental corruption and many offline record edits. It is **not a digital signature** and is not tamper-proof against an actor who can rewrite the database, recompute the chain, or remove triggers. Production deployments must export audit evidence to an independently controlled immutable store or signing service.

## Production admission requirements still outstanding

A production deployment must supply and independently validate all of the following:

- An audited KMS/HSM-backed authenticated-encryption provider using AES-256-GCM, unique nonces, authenticated associated data, immutable key-version IDs, rotation, revocation, and recovery procedures.
- A shared durable repository with tenant isolation, transactions, compare-and-swap on credential generation and account revision, and cross-process/cross-node consistency.
- Atomic account-record plus audit-event commits and an independently protected immutable audit sink.
- Operational monitoring for KMS failures, stale generations, identity mismatches, rotation conflicts, and audit-chain verification failures.
- Backup, restore, key-retention, disaster-recovery, and access-review evidence.
- Separate per-user authorization and secret isolation before enabling multi-user real-account access.

The SQLite adapter intentionally fails the production-admission gate. Setting a provider/repository declaration flag is not a substitute for a security review or deployment evidence.

## Trading safety boundary

Credential rotation and key rewrapping do not grant order-write authority. Live order writing remains disabled by default, and these tests use fake providers/exchanges. No real Delta API credentials or live orders are part of this phase. Passing these tests demonstrates selected software properties only; it does not establish profitability or full production readiness.
