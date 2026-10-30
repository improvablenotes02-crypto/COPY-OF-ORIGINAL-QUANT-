# Phase 213 — Canonical PAPER deployment profile

## Purpose

Provide an explicit deployment wrapper for the canonical `build_paper_engine()` startup path without silently changing frozen legacy startup modules, existing library callers, or strategy artifacts.

## Configuration

- `QE_PAPER_DATA_GATE_PROFILE=compat` (default): preserve legacy behavior. If `QE_PAPER_DATA_MAX_AGE_SECONDS` is set to a valid finite, non-negative number, the canonical engine uses the optional gate; otherwise the gate remains disabled.
- `QE_PAPER_DATA_GATE_PROFILE=strict`: requires `QE_PAPER_DATA_MAX_AGE_SECONDS` to be set to a valid finite, non-negative number. Startup raises `ValueError` if it is missing or invalid. The strict requirement is propagated by `RealTimeEngine` to newly created `PaperRuntime` instances.
- Any other profile value fails startup rather than silently choosing a mode.

Example (PowerShell):

```powershell
$env:QE_PAPER_DATA_GATE_PROFILE = "strict"
$env:QE_PAPER_DATA_MAX_AGE_SECONDS = "30"
# In the PAPER startup path, replace build_paper_engine() with:
from core.runtime.paper_gate_profile import build_profiled_paper_engine
engine, manager = build_profiled_paper_engine()
```

Use a maximum age appropriate to the market-data timeframe and latency. A permissive threshold can still admit stale data; a strict profile is only as strong as its threshold and timestamp/source quality.

## Scope boundary

Use `build_profiled_paper_engine()` from `core.runtime.paper_gate_profile` in deployment startup when this profile should be applied. The legacy `build_paper_engine()` remains unchanged and does not automatically read these environment variables. The wrapper validates configuration first, builds the engine, then applies the gate settings before the caller starts or reconciles it. Do not start/reconcile the returned engine before the wrapper returns. This does not guard direct construction of legacy `PaperTradingEngine`, `VerifiedPaperRuntime`, or direct `PaperRuntime` calls outside the canonical builder. Those paths still require explicit gated adapters or their own configuration. No claim of universal enforcement is made.

## Safety and validation

The profile validates configuration locally and performs no network calls. It does not enable live trading or change broker order-write behavior. Delta-focused integration remains distinct from uncertified NSE, Sensex, and forex adapters.
