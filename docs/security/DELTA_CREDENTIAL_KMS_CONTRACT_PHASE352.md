# Vendor-neutral KMS integration and admission contract — Phase 352

## Status and scope

Phase 352 defines the integration boundary for a production credential-encryption provider. It does not implement a cloud-vendor client, claim cryptographic certification, change the Delta account registry's production-admission decision, or authorize real-account trading.

The registry continues to depend on the existing `EncryptionProvider` interface (`encrypt` and `decrypt`) and injects tenant/account-scoped associated data. A deployment-specific adapter may implement that interface by calling an approved KMS or HSM. The adapter must not persist plaintext credentials, expose key material, or silently fall back to local/test encryption.

## Required adapter contract

A production candidate must demonstrate all of the following with vendor documentation, implementation review, and executable conformance evidence:

1. **Authenticated encryption:** AES-256-GCM with a unique nonce for every encryption under a given key. The nonce and authentication tag must be retained in an unambiguous, versioned ciphertext envelope. No unauthenticated encryption mode is admissible.
2. **Authenticated associated data:** pass the exact registry-provided associated data to both encryption and decryption. A change to tenant, internal account ID, venue, region, or environment must make decryption fail authentication.
3. **Immutable key identity:** each envelope records a stable, immutable key-version identifier, not a mutable alias such as `current`. Decryption must use the exact recorded version.
4. **Rotation and rewrap:** new writes use the configured active key version. Rewrap decrypts with the recorded old version and encrypts with the active version without changing the Delta API key/secret. Rotation and rewrap remain separate audited operations.
5. **Key lifecycle:** define key creation, activation, disablement, revocation, retention, backup/recovery, and destruction. Old versions must remain decryptable until all dependent records and approved backups have been rewrapped or retired under a documented recovery decision.
6. **Least privilege:** runtime identity may perform only the required encrypt/decrypt operations on the designated key scope. Key administration and policy changes use a separate privileged identity and approval path.
7. **Failure behavior:** timeouts, throttling, authorization failures, unavailable key versions, malformed envelopes, and authentication failures fail closed. No plaintext fallback, alternate-key guessing, automatic credential substitution, or retry that changes account identity is allowed.
8. **Redaction:** exceptions returned to callers must not contain API key/secret values, plaintext payloads, ciphertext, nonce/tag material, access tokens, or raw vendor response bodies. Diagnostic events use stable error categories and correlation IDs only.
9. **Observability:** emit non-secret metrics for operation outcome, latency, throttling, key-version usage, and authentication failures. Never place credentials or ciphertext in logs, traces, metrics, or audit events.
10. **Independent evidence:** provider claims such as `production_ready=True` and `algorithm="AES-256-GCM"` are declarations only. They are not evidence of algorithm correctness, KMS configuration, key custody, access policy, or operational readiness.

## Envelope and associated-data requirements

The persisted envelope must be versioned and carry, at minimum, the immutable key-version ID, algorithm identifier, nonce, ciphertext, and authentication tag (or a documented provider envelope that preserves these fields without ambiguity). The serialization must be canonical and bounded before parsing. Unknown envelope versions, algorithms, missing fields, oversized values, and invalid encodings are rejected.

Associated data is supplied by the account registry and must be authenticated byte-for-byte. The adapter must not silently normalize, omit, reorder, or replace it. Tests must prove cross-tenant and cross-account ciphertext substitution fails authentication.

## Conformance test matrix

Before a provider can be considered for production admission, a vendor-neutral conformance suite must cover:

- round-trip encryption/decryption with binary and UTF-8 payloads;
- fresh nonce on repeated encryption of identical plaintext;
- tampered ciphertext, nonce, tag, key ID, and associated data rejection;
- cross-tenant, cross-account, venue, region, and environment substitution rejection;
- exact immutable key-version selection during decrypt;
- active-key change followed by successful rewrap and unchanged plaintext;
- old-key disablement behavior and documented recovery behavior;
- KMS timeout, throttling, permission denial, missing key, and malformed response fail-closed behavior;
- concurrent encryption and rewrap requests;
- no secret material in exceptions, logs, traces, metrics, or audit events;
- bounded resource use and explicit timeout behavior.

Test doubles may validate adapter control flow but cannot establish cryptographic security. At least one integration test must run against the selected provider's isolated non-production KMS environment. Independent security review and operational evidence remain mandatory.

## Deployment and admission sequence

1. Select a KMS/HSM vendor and deployment boundary; record data residency and regulatory constraints.
2. Implement the adapter outside the generic registry, preserving the existing `EncryptionProvider` interface.
3. Complete the conformance suite and vendor sandbox integration tests.
4. Review key policy, runtime identity, network path, audit export, rotation, revocation, backup, restore, and disaster-recovery procedures.
5. Export credential audit events to an independently controlled immutable sink and verify integrity after restore.
6. Implement and certify a shared durable multi-user repository with tenant isolation and cross-process compare-and-swap.
7. Complete per-user authorization, secret isolation, operational monitoring, incident response, and independent security review.
8. Only after all evidence is reviewed may a separate release decision consider real Delta account onboarding. Live order writing remains a separate safety gate and is not enabled by this phase.

## Explicit non-goals

- No cloud vendor or KMS product is selected by this phase.
- No real API keys or secrets are used.
- No live Delta account is connected and no order is submitted.
- No local/test provider is promoted to production.
- No production-readiness or profitability claim is made.

## Phase 352 exit criteria

The architecture boundary and evidence requirements are documented and reviewable. The current SQLite repository remains `production_ready=False`; the existing declaration-based admission check is not upgraded by this document. Production readiness remains **NOT CERTIFIED / HOLD** pending a selected provider, independently reviewed implementation, conformance and sandbox evidence, shared durable storage, immutable external audit, tenant authorization, and full operational certification.
