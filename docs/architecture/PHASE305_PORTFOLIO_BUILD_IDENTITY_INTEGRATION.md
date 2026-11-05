# Phase 305 — Portfolio Build Identity Integration

## Contract

The typed `EngineBuildIdentity` path is verified through the multi-symbol portfolio replay boundary, not only the single-symbol backtester. The portfolio API binds the same canonical build fingerprint into the combined evidence envelope after every symbol payload and cross-leg provenance record has passed validation.

## Verification

The integration test supplies a two-symbol portfolio with reversed mapping insertion order, passes an `EngineBuildIdentity` object, and verifies the resulting evidence uses sorted symbols and the expected engine fingerprint.
