# Phase 289 — Provenance-gated canonical backtesting

Status: implementation and tests committed; exact-SHA CI and strict-manifest
verification pending.

## Boundary

The canonical event-driven Backtester now exposes run_scoped(candles,
provenance_records, journal=None). It validates the complete provenance set
through the Phase 288 admission contract before invoking the existing replay
method. Validation failures occur before any candle is processed.

## Compatibility

The legacy run() method is unchanged to avoid breaking historical research
fixtures and older callers. New venue-, region-, environment-, or account-aware
backtests must use run_scoped(). This additive API does not silently infer
provenance for legacy datasets.

## Guarantees and limits

The scoped entry point rejects empty, malformed, incomplete, cross-venue,
cross-region, cross-environment, mixed public/private, and mismatched private
account datasets according to Phase 288 rules. Tests exercise pre-replay
rejection and successful forwarding to the canonical replay implementation.

This does not yet force every direct caller of legacy run() or every other
research runner to supply provenance. Those entry points require separate
migration and compatibility work. Provenance is only as trustworthy as the
authenticated source adapter that creates it. No live orders, credentials, or
production account access are involved; live order writing remains disarmed.
