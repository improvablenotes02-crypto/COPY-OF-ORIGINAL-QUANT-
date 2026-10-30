# Phase 216 — strict PAPER no-start preflight

## Purpose

Phase 215 introduced an explicitly selected strict-profile PAPER launcher. Phase 216 adds a preflight-only CLI mode so operators can validate deployment configuration without constructing an engine, starting monitoring, or entering a broker workflow.

## Usage

PowerShell:

```powershell
$env:QE_PAPER_DATA_GATE_PROFILE = "strict"
$env:QE_PAPER_DATA_MAX_AGE_SECONDS = "15"
python -m core.runtime.strict_profiled_paper_launcher --preflight
python -m core.runtime.strict_profiled_paper_launcher --preflight --json
```

Use a max-age threshold that matches the feed interval and operational policy; `15` is only an example. JSON output is limited to the validated policy and explicit no-start status flags. It does not include environment dumps, credentials, or broker settings.

## Behavior

- Requires `QE_PAPER_DATA_GATE_PROFILE=strict`.
- Requires a finite, non-negative `QE_PAPER_DATA_MAX_AGE_SECONDS` value through the canonical profile validator.
- Rejects missing, compatibility, malformed, non-finite, or negative configuration.
- `--preflight` exits without building an engine or invoking the PAPER monitoring runner.
- `--json` is valid only with `--preflight`.
- The normal command without `--preflight` still invokes the explicit strict PAPER launcher.

## Scope and limitations

This is a configuration preflight, not a connectivity test, feed-freshness observation, exchange integration certification, or proof that every legacy startup path is gated. The frozen legacy `main.py` remains unchanged and does not automatically select the strict launcher. This phase adds no live-order path and does not change strategy artifacts.

## Validation

Phase 216 tests exercise the pure validation API, invalid-profile and invalid-threshold rejection, and subprocess-level CLI success/failure. Targeted tests are run separately so each invocation's exit status and snapshot-guard result remain visible. The full repository test suite is not certified by this phase.
