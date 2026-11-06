# Delta credential lifecycle and revocation boundary

## Current behavior

The account registry encrypts credentials before persistence and creates a read-only
exchange client when a session is opened. Before each exposed exchange operation, the
session re-reads its account record and checks that its scope, credential envelope,
and update generation still match the record used to create the client. Deleting the
account, binding/changing its provider identity, or changing its credential record
therefore causes the next operation to fail closed. A repository read failure also
fails closed. This check can invalidate sessions across processes only when the
injected repository itself is shared and provides sufficiently fresh reads; the
included SQLite repository is local development/test storage.

This is a check-before-use guard, **not an atomic distributed lease**. If deletion or
rotation races after the authorization check but before or during an exchange request,
that already-started request may complete. The next operation will be rejected. Strong
revocation requires a server-side lease/generation protocol with defined consistency
and in-flight request handling, plus venue-side API-key revocation.

Credential replacement is not currently implemented as an atomic rotation operation.
Do not treat deleting and re-registering an account as a safe rotation procedure.

## Required production lifecycle

1. **Rotation:** implement a versioned credential record and an atomic compare-and-swap
   update. Encrypt the new key pair with authenticated associated data bound to the
   tenant, internal account ID, venue, region, environment, and credential version.
   Preserve audit evidence without retaining plaintext.
2. **Session invalidation:** the current implementation performs a repository-backed
   preflight check before each operation and rejects stale sessions. Upgrade this to
   server-side session leases with a monotonic account credential generation and
   explicitly defined in-flight request semantics. A rotation or deletion must
   invalidate stale sessions across processes; a check-before-use alone cannot cancel
   an operation that has already passed its check.
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
