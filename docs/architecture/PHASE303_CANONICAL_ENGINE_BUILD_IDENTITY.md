# Phase 303 — Canonical Engine Build Identity

## Contract

`EngineBuildIdentity` provides a typed, deterministic descriptor for the QuantEngine build. It binds:
- Release version.
- Source revision (40- or 64-character lowercase Git revision).
- Build artifact SHA-256.
- Dependency-lock SHA-256.
- Runtime identity, including interpreter/platform details.

Its `fingerprint` property canonicalizes these fields as sorted compact JSON and returns SHA-256. That digest can be supplied as `engine_fingerprint` to the evidence-bearing scoped backtest APIs.

## Caller responsibility

The caller must derive artifact and dependency hashes from the exact release artifacts and lock file used by the running process. This descriptor validates format and deterministically combines the supplied values; it does not independently inspect the filesystem or attest to the build pipeline.

## Verification

Tests prove deterministic output and verify that changing any one build component changes the fingerprint. Malformed revisions and hashes are rejected.
