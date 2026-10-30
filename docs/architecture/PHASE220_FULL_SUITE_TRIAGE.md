# Phase 220 — Full-suite execution and failure triage

## Objective

Move beyond test collection and run a broader regression slice while recording the full-suite execution limit honestly. No strategy logic, broker order-write behavior, credential files, or legacy `main.py` were changed.

## Canonical full-suite attempt

Command:

```bash
python -m pytest tests/ -q
```

Outcome: **timed out at the 600-second command limit**. The output showed progress to roughly 12% before the process was terminated by the execution limit. This is an incomplete run, not a passing or failing full-suite result. A second verbose probe was stopped during the 120-second diagnostic window; its log showed progress through approximately 22%, with the last visible test passing. No root cause for the duration has been proven by this phase.

## Targeted regression batch

The following 15 test modules were run together in a separate pytest invocation:

- digest recertification and authoritative-path checks
- continuity and strategy-identity separation
- Phase 214–218 strict PAPER launcher and preflight checks
- Phase 204–209 data-quality and runtime-gate checks

Result: **92 passed, 1 skipped in 11.83 seconds**. The snapshot guard reported 15 test modules executed, `files_added_by_tests: []`, no restores, and a pristine tree at session start.

The skipped test remains a skip; it is not counted as a pass. A separate initial invocation had an invalid test filename and exited before running tests; it was corrected and is not part of the successful batch result.

## Bounded audit helper

Added `scripts/phase220_bounded_test_audit.py`, which runs each selected test file in its own subprocess with a configurable timeout and writes a JSON summary. It helps isolate slow or failing modules and preserves results from modules completed earlier. It does not replace `python -m pytest tests/ -q` and does not establish a full-suite pass by itself.

Example:

```powershell
python scripts/phase220_bounded_test_audit.py tests/test_phase218_preflight_deployment_smoke.py tests/test_phase216_strict_paper_preflight.py --timeout-seconds 90 --output phase220_smoke.json
```

## Interpretation and limits

- The selected regression batch passed, with one intentional/fixture-controlled skip.
- The full suite remains **uncertified** because the canonical run exceeded the available execution window.
- Do not interpret the timeout as proof of a test defect. Isolate slow modules with the bounded audit helper and triage failures individually.
- No live orders were submitted. This phase does not certify live feeds, broker connectivity, profitability, or production readiness.
- The strict PAPER launcher remains explicitly selected; legacy `main.py` was not modified.
