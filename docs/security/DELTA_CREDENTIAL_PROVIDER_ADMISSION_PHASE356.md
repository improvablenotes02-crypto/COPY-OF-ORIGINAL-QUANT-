# Phase 356 — Production credential admission requires behavioral conformance

Production-mode Delta account registry construction now runs the vendor-neutral credential-provider conformance assessment after checking the provider and repository production declarations. A provider that declares AES-256-GCM and production readiness but fails the behavioral contract is rejected before account credentials can be registered.

The assessment is cached for the lifetime of the exact provider object so that normal account writes do not repeatedly call the KMS with test vectors. Replacing the provider object invalidates the cached assessment and forces a new check. Deployments must restart/reassess after changing provider configuration or KMS policy; the assessment is not a substitute for provider-specific rotation and policy monitoring.

## Limits

This is a behavioral admission gate, not cryptographic certification. The test provider used by the tests is deliberately non-production and does not implement AES-GCM. A passing assessment cannot prove key custody, attestation, KMS configuration, tenant isolation, durable storage, or deployment security. The separate production declarations and independent evidence requirements remain mandatory.

No real Delta credentials or live accounts are used. Live order writing remains disarmed. Production readiness remains NOT CERTIFIED / HOLD.
