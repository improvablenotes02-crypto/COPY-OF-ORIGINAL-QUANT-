# Phase 210 — Paper-entrypoint gate inventory

## Result

This phase maps the known paper candle entrypoints and pins their protection
status with tests. It does not change runtime behavior or enable live trading.

| Entry point | Quality gate | Default status | Notes |
|---|---|---|---|
| `RealTimeEngine` → `PaperRuntime.process_closed_candle` | `PaperRuntime` intake gate | **Opt-in** | Pass a finite, non-negative `market_data_max_age_seconds`; the orchestrator propagates it to newly created runtimes. |
| Direct `PaperRuntime.process_closed_candle` | `PaperRuntime` intake gate | **Opt-in** | Direct callers can bypass quality checks if they leave the threshold `None`. |
| `GatedPaperTradingEngine.run_candle` | Gate before base engine | **Required** | Construction requires `market_data_max_age_seconds`; rejected candles do not reach the base engine. |
| `GatedVerifiedPaperRuntime._on_verified_candle` | Gate before paper sink | **Required** | Construction requires `market_data_max_age_seconds`; rejected candles do not reach the paper sink. |
| Legacy `PaperTradingEngine.run_candle` | No Phase 204+ intake gate in this class | **Ungated legacy API** | Remains available for compatibility; callers requiring the gate should use `GatedPaperTradingEngine`. |
| Legacy `VerifiedPaperRuntime` | No Phase 204+ intake gate in this class | **Ungated legacy API** | Remains available for compatibility; callers requiring the gate should use `GatedVerifiedPaperRuntime`. |

## Security interpretation

- There is **not** a universal, always-on market-data gate across every paper API.
- The canonical `RealTimeEngine` is protected only when configured with an age
  threshold. `None` intentionally preserves legacy behavior.
- The two explicitly gated adapters require a threshold at construction and
  fail closed when gate evaluation errors.
- This inventory is based on the currently identified in-repository entrypoints;
  it is not proof that every downstream caller or external integration uses a
  gated entrypoint. New entrypoints should be added to this inventory and tests.
- A freshness gate is not a substitute for exchange-specific schema validation,
  market-session checks, sequence-gap detection, or execution authorization.
- No external API calls or exchange order writes were performed for this phase.
  Live trading remains on HOLD. No NSE, Sensex, or forex adapter is certified by
  this work.

## Validation

`tests/test_phase210_paper_entrypoint_inventory.py` checks the opt-in defaults,
required constructor threshold for gated wrappers, and continued distinction
between gated and legacy APIs. Existing Phase 205–209 tests separately exercise
actual stale/fresh candle behavior and propagation through the canonical route.
