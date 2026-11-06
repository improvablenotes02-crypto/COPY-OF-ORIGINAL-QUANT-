# Phase 355 — Repeated envelope validation and provider error redaction

Phase 355 closes two gaps in the vendor-neutral provider conformance harness.

1. The second encryption result is validated independently. It must be a non-empty envelope with a non-empty key-version ID, the same declared algorithm as the first envelope, and non-empty byte ciphertext. A malformed second result cannot pass merely because the first result was valid.
2. Decryption failures are exercised with a test provider that deliberately raises secret-bearing exception text. The conformance report must contain only stable check identifiers and must never echo provider exception text.

The tests use local test doubles only. They do not implement or certify AES-GCM, a KMS, HSM, key custody, or production deployment. The provider must still pass vendor-specific cryptographic and operational review before admission.

No live credentials, production API keys, or live order execution are introduced. Live execution remains disarmed; production readiness remains NOT CERTIFIED / HOLD.
