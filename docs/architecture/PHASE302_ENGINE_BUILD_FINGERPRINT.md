# Phase 302 — Engine Build Fingerprint in Execution Identity

## Contract

A complete scoped execution fingerprint now requires three SHA-256 inputs supplied together:
- Strategy artifact fingerprint.
- Effective strategy configuration fingerprint.
- QuantEngine engine/build fingerprint.

The combined execution identity includes these three fingerprints plus the validated candle payload hash and complete dataset provenance fingerprint. Supplying only a subset is rejected before replay. Dataset-only evidence remains supported when all three are omitted; its execution fingerprint is explicitly null.

## Caller responsibility

The caller must compute the engine fingerprint from a canonical build artifact or immutable release identity. The engine validates digest shape and binds the supplied value; it does not independently hash the entire source tree or attest to the build pipeline.

## Verification

Tests cover partial fingerprint rejection, malformed digest rejection, and execution-identity changes when the engine build changes while all data and strategy inputs remain identical.
