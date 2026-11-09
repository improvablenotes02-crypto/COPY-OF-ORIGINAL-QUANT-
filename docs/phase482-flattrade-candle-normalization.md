# Phase 482 - Flattrade TPSeries candle normalization

The new normalizer maps Flattrade's documented `TPSeries` fields:
- `time` -> timezone-aware UTC timestamp, parsed as India local time
- `into` / `inth` / `intl` / `intc` -> OHLC
- `intv` -> interval volume

It supports the documented day-first dash and slash timestamp renderings. It rejects missing fields, invalid OHLCV, unsupported intervals, duplicate timestamps and out-of-order rows. It does not substitute total-session volume (`v`) for missing interval volume (`intv`).

This normalizer is a deterministic conversion boundary only. It does not certify that rows are final, fresh, gap-free, exchange-authentic, or aligned to a valid market session. It is not wired into the production strategy runtime or paper execution.
