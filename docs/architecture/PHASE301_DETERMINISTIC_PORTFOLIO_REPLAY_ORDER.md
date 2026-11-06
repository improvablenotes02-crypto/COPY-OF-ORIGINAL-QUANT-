# Phase 301 — Deterministic Scoped Portfolio Replay Order

## Contract

Both `PortfolioBacktester.run_scoped()` and `run_scoped_with_evidence()` now replay symbols in sorted canonical symbol order after every input leg has passed provenance and payload validation.

This removes dictionary insertion order as an implicit risk-allocation input. It matters when shared portfolio capital or risk limits cause earlier symbols to reserve capacity before later symbols are evaluated.

## Compatibility

The legacy unscoped `run()` method retains its existing caller-provided order. Only the provenance-gated scoped entry points impose canonical ordering. The order is deterministic and visible in the evidence symbol tuple.

## Verification

Tests supply identical portfolios with reversed history/provenance mapping insertion order and verify that both scoped APIs execute symbols in the same sorted order.
