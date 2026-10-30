# Phase 235 — Explicit manifest payload-digest assurance

The release verifier already validates each archived payload's SHA-256 against
`BUILD_MANIFEST.sha256`. Phase 235 makes that specific assurance visible in the
detached release record as `Manifest payload digests: PASS` and requires the
field when validating a detached record. This avoids ambiguity between path
coverage and cryptographic payload verification.

Regression coverage rejects a record that omits the explicit digest assurance.
This remains a local release-integrity check; it does not substitute for hosted
Ubuntu/Windows CI, full-suite certification, exchange/broker validation, or
production approval. Live order placement remains disabled/on hold.
