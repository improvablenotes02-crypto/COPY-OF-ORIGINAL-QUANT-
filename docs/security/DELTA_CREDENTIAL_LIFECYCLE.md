# Delta credential lifecycle and revocation boundary

## Current behavior

The account registry encrypts credentials before persistence and creates a read-only
exchange client when a session is opened. The returned session retains that client.
Deleting an account removes its persisted registry row; it does **not** revoke a
credential at Delta, and it does not invalidate an exchange client that was already
constructed. A caller holding an existing session may continue making the methods
exposed by that read-only facade until the client or process is shut down.

Credential replacement is not currently implemented as an atomic rotation operation.
Do not treat deleting and re-registering an account as a safe rotation procedure.

## Required production lifecycle

1. **Rotation:** implement a versioned credential record and an atomic compare-and-swap
   update. Encrypt the new key pair with authenticated associated data bound to the
   tenant, internal account ID, venue, region, environment, and credential version.
   Preserve audit evidence without retaining plaintext.
2. **Session invalidation:** add server-side session leases with an account credential
   generation. Check the generation before every exchange operation. A rotation or
   deletion increments the generation so stale sessions fail closed. This must work
   across processes; an in-memory registry is insufficient.
3. **Venue-side revocation:** separately revoke the old API key in the Delta account
   security settings/API workflow. Local deletion cannot revoke a venue credential.
4. **Failure handling:** if persistence, KMS, or invalidation is unavailable, do not
   fall back to an old credential or silently create another session.
5. **Audit:** record actor, tenant/account IDs, credential version, operation, outcome,
   and timestamp. Never record API key/secret values, ciphertext, decrypted payloads,
   or provider exception text.
6. **Live gate:** rotation, revocation, and session invalidation must be tested under
   concurrent requests, process restart, and partial failure before real-account
   trading is considered.

## Current deployment decision

The SQLite repository remains development/test-only. Production credential admission
is a declaration-based guard, not a cryptographic attestation. No production KMS-backed
AES-256-GCM implementation or distributed session-revocation service is certified.
Real Delta account registration and live order execution therefore remain on HOLD.
