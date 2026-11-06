# Phase 307 — Canonical Effective Configuration Fingerprinting

## Contract

`hash_canonical_json()` computes a deterministic SHA-256 digest for JSON-compatible configuration values. Object keys must be strings; values may be null, strings, booleans, finite numbers, arrays/tuples, and nested objects. Non-finite numbers, sets, arbitrary objects, and non-string object keys are rejected rather than serialized ambiguously.

`BacktestConfigurationIdentity.from_configuration()` builds a typed configuration identity from the effective configuration object, version, and parameter-schema version.

Object insertion order does not affect the digest; array order does.

## Caller responsibility

The caller must pass the effective configuration after defaults and overrides have been resolved. Hashing a partial user-supplied configuration would not identify the actual runtime settings.

## Verification

Tests cover mapping-order independence, list-order sensitivity, the typed identity factory, and rejection of non-finite or non-JSON values.
