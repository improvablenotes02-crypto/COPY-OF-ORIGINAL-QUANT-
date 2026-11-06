# Phase 291 — Replay Payload Hash Binding

## Contract

`Backtester.run_scoped()` now materializes the requested candle iterable and verifies it before calling the replay engine. The canonical digest uses the frozen Phase 11G rule: JSON serialization with sorted keys followed by SHA-256.

Each row covers timestamp, OHLCV, closed state, and candle symbol. The validator rejects malformed/non-finite rows, invalid OHLC geometry, negative volume, forming candles, row-count mismatch, populated candle-symbol mismatch, and digest mismatch. The validated immutable tuple—not the original potentially one-shot iterator—is passed to replay.

`PortfolioBacktester.run_scoped()` applies the same verification independently to every symbol before starting any engine, then enforces portfolio-wide venue/region/environment/data-class/account compatibility.

## Compatibility and limitations

Legacy `run()` remains available and is not hash-gated. Existing datasets must calculate `dataset_hash` using the documented canonical candle-row representation before using `run_scoped()`. This binds the supplied replay payload to its declared digest; it does not authenticate the original exchange, prove timestamp atomicity, or establish strategy profitability. It does not authorize live order writes.

## Verification

Adversarial tests cover payload tampering, row-count and symbol mismatch, forming candles, invalid numeric/geometry values, and portfolio preflight atomicity. Exact-SHA runtime CI is required for certification.
