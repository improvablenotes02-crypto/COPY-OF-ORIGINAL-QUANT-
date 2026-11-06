# Phase 354 — Credential key-version binding

## Scope

The vendor-neutral credential-provider conformance harness now verifies two additional observable properties:

- **Key-version stability:** two encryptions performed during one assessment must identify the same active key version. This assessment assumes the provider's active-key configuration is stable for the duration of the short conformance run; a concurrent rotation should cause a fail-closed result and a retry of the assessment under a stable configuration, not acceptance of mixed key versions.
- **Key-version binding:** decrypting an otherwise valid envelope after changing only its key-version identifier must fail. Providers must resolve the exact immutable key version named by the envelope and must not silently substitute the active key or another version.

## Limits

These are behavioral contract checks, not cryptographic certification. The Phase 353 test provider is a deliberately non-production test double, not AES-256-GCM and not a KMS. Passing these checks does not prove key custody, provider attestation, cryptographic strength, key immutability, rotation correctness under production load, or tenant isolation. Those require a selected KMS, provider-specific integration tests, deployment controls, and independent security review.

No live credentials are introduced. No real Delta account is connected. Live execution remains disarmed, and production readiness remains NOT CERTIFIED / HOLD.
