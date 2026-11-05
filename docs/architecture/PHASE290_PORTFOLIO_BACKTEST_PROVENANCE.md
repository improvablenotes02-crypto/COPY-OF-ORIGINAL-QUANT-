# Phase 290 — Portfolio Backtest Provenance Admission

## Contract

`PortfolioBacktester.run_scoped(history, provenance_by_symbol, journal=None)` is the supported provenance-gated entry for multi-symbol replay.

Before any symbol engine runs, it requires:
- a non-empty history mapping and a provenance mapping with exactly the same symbol keys;
- at least one complete, validated scope record for each symbol;
- each record's symbol to equal its portfolio key;
- a single venue, region, environment, data class, and (for private account data) exact tenant/internal/provider account identity across every portfolio leg;
- complete pagination evidence for every dataset.

Any failure raises `ScopeProvenanceError` before the first replay call. This prevents a portfolio from partially replaying before a later symbol's incompatible provenance is discovered.

## Compatibility and limitations

The legacy `run()` method remains unchanged for existing research callers. It is not provenance-gated and must not be treated as suitable for untrusted or account-scoped datasets. The new method is an admission boundary, not a proof that a source is authentic, that timestamps are exchange-atomic, or that a strategy is profitable. It does not authorize live order writes.

## Verification

The Phase 290 adversarial tests are included in the runtime data-gate workflow. Exact-SHA CI is required before this phase is certified.
