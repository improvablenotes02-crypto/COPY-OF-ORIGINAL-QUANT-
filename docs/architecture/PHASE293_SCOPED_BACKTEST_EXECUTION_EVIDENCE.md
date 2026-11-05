# Phase 293 — Scoped Backtest Execution Evidence

## Contract

The existing `run_scoped()` APIs retain their original return types. New additive methods, `Backtester.run_scoped_with_evidence()` and `PortfolioBacktester.run_scoped_with_evidence()`, return a `ScopedBacktestOutcome` containing the normal strategy result plus immutable `BacktestExecutionEvidence`.

Evidence records the validated dataset provenance objects, sorted symbol identities, per-symbol row counts, and a deterministic SHA-256 digest over the ordered symbol/dataset-digest/count tuples. For a portfolio, mapping insertion order does not affect the evidence digest.

Every candle payload is revalidated against its dataset provenance before the first replay engine runs. Duplicate dataset symbols and symbol/payload mapping mismatches are rejected. Portfolio-wide venue, region, environment, data-class, and private-account compatibility remains enforced.

## Intended use

Persist the evidence envelope alongside a backtest report, strategy version, configuration snapshot, and application-level run ID. This enables later report inspection to identify the exact declared data inputs.

## Limitations

The evidence digest is a deterministic identity for validated input payloads, not a signature, exchange attestation, immutable external timestamp, or proof that the strategy result is profitable. It does not include strategy source/configuration unless the caller records those separately. It does not authorize or enable live order writing.

## Verification

The Phase 293 runtime suite tests deterministic single-symbol and portfolio evidence, mapping-order independence, tamper rejection, and pre-replay fail-closed behavior. Exact-SHA Linux/Windows CI and strict manifest verification are required before certification.
