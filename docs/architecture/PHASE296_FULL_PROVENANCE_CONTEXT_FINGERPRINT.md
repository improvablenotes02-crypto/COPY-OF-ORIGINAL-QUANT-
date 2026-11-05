# Phase 296 — Full Provenance Context Fingerprint

## Contract

Execution evidence now carries a separate `provenance_fingerprint` computed from the complete validated dataset scope in symbol-sorted canonical form. It includes venue, region, environment, instrument, symbol, timeframe, data class, source, source timestamp, schema and normalization versions, dataset digest, row count, completeness/pagination state, and exact tenant/internal/provider account identity for private data.

The combined `execution_fingerprint`, when strategy and configuration fingerprints are supplied, now binds:
- Canonical candle payload identity.
- Complete dataset provenance context.
- Strategy artifact fingerprint.
- Effective configuration fingerprint.

Consequently, identical OHLCV candles from a sandbox versus production environment, a different source, or a different private account do not share the same provenance/execution identity.

## Compatibility

The existing `payload_hash` remains the candle-payload aggregate identity. The new `provenance_fingerprint` is a separate context identity. Dataset-only evidence remains possible when strategy/configuration fingerprints are omitted; in that case the combined execution fingerprint remains null.

## Verification

Tests confirm same-candle/different-environment separation, source identity separation, private-account identity separation, and deterministic fingerprints for identical complete provenance.
