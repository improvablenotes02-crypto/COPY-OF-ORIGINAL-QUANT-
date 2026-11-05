# Phase 294 — Strategy and Configuration Fingerprints

## Contract

The evidence-bearing scoped replay APIs accept SHA-256 fingerprints for the strategy artifact, its effective configuration, and the QuantEngine build. All three must be supplied together and each must be exactly 64 lowercase hexadecimal characters.

When all three are supplied, the evidence envelope computes a deterministic execution fingerprint over the validated payload digest, complete provenance fingerprint, strategy fingerprint, configuration fingerprint, and engine build fingerprint. Changing any one changes execution identity without changing the candle payload identity.

When none are supplied, dataset-only evidence remains available and `execution_fingerprint` is null. Partial fingerprint sets are rejected. This makes the distinction explicit: dataset identity alone is not a complete reproducibility claim.

## Caller responsibility

The caller must compute strategy and configuration fingerprints from canonical, versioned artifacts. The engine validates digest shape and binds the values; it does not independently inspect strategy source files, serialize arbitrary runtime configuration, or attest that a fingerprint was honestly derived.

## Verification

Tests cover valid paired fingerprints, strategy-change sensitivity, incomplete pairs, malformed digests, pre-replay rejection, and dataset-only compatibility. Exact-SHA CI is required for certification.
