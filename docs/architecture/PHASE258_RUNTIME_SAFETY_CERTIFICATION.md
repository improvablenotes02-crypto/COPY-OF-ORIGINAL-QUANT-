# Phase 258 — Paper runtime gate construction hardening

## Scope

Phase 258 hardens the hand-off from the canonical PAPER deployment profile to the canonical multi-symbol runtime. It does not enable live execution or claim that all legacy runtime entry points are protected.

## Change

- build_profiled_paper_engine() resolves and validates the deployment profile before invoking the engine builder.
- The validated maximum-age threshold and required-gate flag are passed into build_paper_engine().
- build_paper_engine() forwards those values into the RealTimeEngine constructor.
- The canonical engine therefore validates the policy during construction. The previous post-construction mutation of engine fields has been removed.
- The injected clock remains unset by the deployment profile so each PaperRuntime uses its UTC clock by default; tests may inject a deterministic clock directly.

## Configuration

Compatibility remains the default for backwards compatibility:

- QE_PAPER_DATA_GATE_PROFILE=compat: gate optional; no freshness threshold by default.
- QE_PAPER_DATA_GATE_PROFILE=strict: threshold is mandatory and must be finite and non-negative.
- QE_PAPER_DATA_MAX_AGE_SECONDS: maximum candle age in seconds.

Strict example (PowerShell):

```powershell
$env:QE_PAPER_DATA_GATE_PROFILE = "strict"
$env:QE_PAPER_DATA_MAX_AGE_SECONDS = "30"
python main.py
```

Choose a threshold appropriate to the instrument, timeframe, and feed latency. A 30-second setting is an example, not a universal recommendation.

## Verification

The dedicated runtime-data-gate GitHub Actions workflow runs the market-data validation, paper quality gate, runtime propagation, canonical engine, central policy, and deployment-profile test modules on Windows and Ubuntu.

Equivalent local command:

```powershell
python -m pytest tests/test_phase203_market_data_validation.py tests/test_phase204_paper_data_quality_gate.py tests/test_phase205_paper_runtime_quality_gate.py tests/test_phase208_canonical_realtime_gate.py tests/test_phase211_central_paper_gate_policy.py tests/test_phase213_paper_gate_deployment_profile.py -q
```

## Explicit limitations / release blockers

- Compatibility remains the default; this phase does not silently change existing deployments to strict mode.
- Direct legacy constructors and alternate runtime entry points are not universally wrapped by this deployment profile.
- Freshness validation does not prove exchange authenticity, feed completeness, venue-session correctness, or instrument metadata correctness.
- The default explicit-symbol universe still labels synthetic SPOT contract metadata as unverified; it is not suitable evidence for derivative-realistic simulation.
- Verified Global market-data transport evidence, reconnect/recovery certification, exchange economics, independent strategy-edge validation, credential rotation, and the full regression disposition remain release blockers.

**Release status: NOT_PRODUCTION_READY / HOLD. Live order writing remains disarmed.**
