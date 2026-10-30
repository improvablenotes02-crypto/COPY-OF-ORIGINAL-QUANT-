# Phase 214 — Profiled PAPER startup integration

## What changed

Added `core.runtime.profiled_paper_entrypoint.run_profiled_paper_with_monitoring()` as a controlled, explicit PAPER startup path. It resolves/validates the deployment profile before building the engine, applies the profile through the Phase 213 wrapper, then passes that same configured engine to the canonical monitoring/lifecycle runner. The runner is injectable for offline tests; errors are propagated rather than falling back to an unprofiled runner.

This is an explicit integration point, not a silent replacement for frozen `main.py` or `core/runtime/paper_main.py`. Deployments must deliberately select this entrypoint. The module does not choose LIVE mode or perform exchange order writes.

## Entry-point audit snapshot

| Path | Gate state | Enforcement | Phase 214 disposition |
|---|---|---|---|
| `run_profiled_paper_with_monitoring` | `strict` | Required threshold validated before engine build; config applied before runner | New explicit controlled path; regression tested |
| `build_profiled_paper_engine` | `strict` | Required threshold validated before builder | Reused by controlled path |
| `build_paper_engine` / legacy `main.py` PAPER branch | `compat` unless caller configures engine | No automatic env-profile integration | Left unchanged for compatibility |
| Direct `PaperRuntime` | Optional | No threshold means legacy behavior | Still needs explicit config/gated caller |
| `GatedPaperTradingEngine` | Required | Gate before base engine | Existing gated alternative |
| `GatedVerifiedPaperRuntime` | Required | Gate before paper sink | Existing gated alternative |
| Direct legacy `PaperTradingEngine` | Ungated legacy API | No Phase 204+ intake gate in class | Remains available; not universally protected |
| Direct legacy `VerifiedPaperRuntime` | Ungated legacy API | No Phase 204+ intake gate in class | Remains available; not universally protected |

## Validation

New tests cover fail-before-build for invalid strict configuration, gate application before runner invocation, propagation of runner failures without fallback, and compatibility defaults. Phase 205–213 targeted tests are also run individually. The full repository suite remains uncertified unless a separate complete run succeeds.

## Safety boundary

The freshness gate cannot guarantee correct source timestamps, sequence continuity, exchange-session validity, or market-specific schema correctness. Live trading remains on HOLD. No exchange APIs or order writes are used by this module or its tests. NSE, Sensex, and forex adapters remain uncertified.
