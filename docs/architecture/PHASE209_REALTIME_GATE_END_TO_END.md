# Phase 209 — Canonical real-time paper gate end-to-end regression

## Goal

Verify the configured market-data quality gate at the actual canonical routing boundary, rather than testing only the gate helper or a stand-alone wrapper.

## Coverage added

- A stale candle routed by `RealTimeEngine._on_closed_candle` reaches its matching `PaperRuntime`, is rejected there, and never reaches the strategy/broker engine.
- A fresh candle is delivered while a malformed follow-up candle is rejected.
- An unknown symbol is not routed to any runtime.
- Universe reconciliation passes the configured maximum age and clock provider into a newly created paper runtime and syncs the same eligible instrument set to subscriptions.

## Design notes

The canonical engine routes by the existing `(exchange, instrument_id)` identity key. The gate remains at `PaperRuntime.process_closed_candle`, the final shared intake boundary for this canonical paper path. This defense-in-depth arrangement means the orchestrator routes candles but does not duplicate validation logic.

The gate remains opt-in for compatibility: callers must set `market_data_max_age_seconds` to enable it. Existing callers with the default `None` continue to use the legacy ungated behavior. The separate gated paper entrypoint wrappers remain opt-in for callers using those independent APIs; this phase does not claim that every arbitrary custom strategy entrypoint is automatically protected.

## Limitations

These tests use simulated candles and an engine spy. They do not establish feed authenticity, live broker behavior, strategy profitability, or exchange execution safety. No external API calls or order writes are made.
