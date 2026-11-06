# Phase 304 — Typed Engine Build Identity Integration

## Contract

The evidence-bearing single-symbol and portfolio scoped replay APIs accept an `EngineBuildIdentity` object directly through `engine_build_identity`. The object is converted to its canonical SHA-256 fingerprint by the shared provenance layer.

Callers may continue to pass a raw `engine_fingerprint` string. If both forms are supplied, the raw digest must exactly match the typed identity's fingerprint; conflicting values fail closed before replay. Invalid object types are rejected.

## Verification

Tests verify direct typed identity binding, evidence-envelope self-verification, conflicting raw/typed identity rejection, and invalid identity type rejection before any replay call.
