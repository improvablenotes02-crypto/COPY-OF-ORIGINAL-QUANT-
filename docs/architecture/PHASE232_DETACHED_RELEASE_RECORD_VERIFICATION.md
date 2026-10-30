# Phase 232 — Detached release-record verification

## Scope

Phase 231 generated a detached SHA-256 record for a deterministic release ZIP. Phase 232 closes the verification loop by validating the detached record against the exact artifact that will be uploaded by CI.

## Implemented

- `scripts/verify_release_candidate.py` exposes `verify_detached_record()` and a `--verify-record ARTIFACT --record RECORD` command mode.
- Verification checks the recorded artifact basename, SHA-256 digest, byte count, ZIP member count, ZIP CRC/integrity, manifest coverage, secret-like member exclusion, and required PASS fields.
- The cross-platform workflow runs positive, tampering, and artifact-name mismatch regression tests.
- After building the candidate, CI re-verifies the candidate and detached record before uploading both as one artifact bundle.
- CI artifact and output naming now use the Phase 232 identifier.

## Local validation evidence

- `tests/test_phase229_reproducible_packaging.py`, `tests/test_phase231_release_candidate.py`, and `tests/test_phase232_detached_record_verification.py`: 8 passed.
- Secret scans: 21 passed, including 18 subtests.
- `compileall`: passed.
- Strict manifest verification: passed.
- Candidate built twice with matching bytes; copied candidate re-verified against its detached record.
- ZIP integrity and manifest coverage: passed; `.env`/`.git` exclusions checked.

## Boundaries

This is local validation only. It does not prove hosted GitHub Actions succeeded; the workflow's Windows and Ubuntu runs must be inspected after execution. The full repository test suite remains uncertified. No broker orders are sent, and live trading remains on hold.
