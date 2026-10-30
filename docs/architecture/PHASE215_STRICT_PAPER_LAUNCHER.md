# Phase 215 — strict-profile PAPER deployment launcher

## What changed

Added `core.runtime.strict_profiled_paper_launcher`, a dedicated deployment entrypoint that rejects a missing or `compat` profile before engine construction, requires `QE_PAPER_DATA_MAX_AGE_SECONDS`, then delegates to the controlled PAPER startup path from Phase 214. Numeric threshold validation remains in the canonical profile policy and rejects invalid/non-finite/negative values before the builder runs. The runner receives the configured engine only after these checks.

## Explicit launch

From the project root, configure the process environment and run:

```bash
# Linux/macOS shell
export QE_PAPER_DATA_GATE_PROFILE=strict
export QE_PAPER_DATA_MAX_AGE_SECONDS=15
python -m core.runtime.strict_profiled_paper_launcher
```

```powershell
# Windows PowerShell
$env:QE_PAPER_DATA_GATE_PROFILE = "strict"
$env:QE_PAPER_DATA_MAX_AGE_SECONDS = "15"
python -m core.runtime.strict_profiled_paper_launcher
```

Choose the max-age threshold to match the intended market-data interval and operational policy; `15` is only an example. Startup fails closed if the profile is missing/not strict or the threshold is missing/invalid.

## Scope and limitations

- This launcher is explicitly PAPER-only and calls the PAPER monitoring lifecycle; it adds no broker order-write path and does not select LIVE mode.
- Frozen legacy `main.py` and `core/runtime/paper_main.py` are not changed. Running the legacy launcher does **not** automatically opt into this strict launcher; deployment must explicitly use the module command above.
- This is a startup/configuration guard, not proof that all constructors or all legacy paths are gated. Existing compatibility constructors remain outside universal enforcement.
- No full-suite certification or live-execution readiness is claimed.

## Validation target

`tests/test_phase215_strict_paper_launcher.py` covers absent/compat profile rejection, missing and malformed threshold rejection before construction, strict configuration before runner handoff, and propagation of lifecycle failures without fallback.
