# Phase 221 — Bounded Audit Reliability

## Purpose

Improve the bounded pytest audit so partial progress is retained and files
that are helpers/scripts rather than actual pytest modules are not mislabeled
as failing tests.

## Changes

- Added `scripts/phase221_test_audit.py` as the Phase 221 runner.
- Writes a JSON checkpoint after each test file completes, including status,
  duration, return code, and a bounded output tail.
- Classifies pytest exit code 5 plus `no tests ran` as `no_tests` rather than
  `failed`; such files are not counted as successful tests either.
- Keeps the existing Phase 220 helper for backward compatibility.
- Does not alter trading logic, frozen strategy files, broker execution, or
  the legacy `main.py` launcher.

## Validation

A nine-file diagnostic batch completed with:

- 8 test modules passed
- 1 candidate file classified `no_tests` (`tests/test_account.py` contains
  a demonstration `main()` and no pytest test functions)
- 0 failures and 0 timeouts in this explicit batch
- Snapshot guard was pristine at session start and end for each invocation.

A prior broad discovery attempt did not finish cleanly while processing
`tests/test_async_refresh_10.py`, despite that module passing in a separate
relative-path invocation. This discrepancy is unresolved and is documented
rather than being represented as a code failure or as a complete suite pass.
The complete repository suite remains uncertified.

## Reproduction

Run from the project root, with output outside the repository so the snapshot
guard does not interpret the live JSON report as an added project file:

```powershell
python scripts/phase221_test_audit.py tests/orderflow/test_price_ladder.py tests/orderflow/test_price_level.py tests/test_account.py tests/test_account_profit_factor_9pb.py tests/test_accounting_9q.py tests/test_allocation_truth_11eprep.py tests/test_api_error_redaction_phase93.py tests/test_api_server_9pf.py tests/test_archive_isolation.py --timeout-seconds 20 --output $env:TEMP\phase221_bounded_audit.json
```

The output reports `passed`, `failed`, `timeout`, and `no_tests` separately.
