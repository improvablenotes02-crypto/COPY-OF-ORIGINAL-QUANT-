# QuantEngine

Private QuantEngine project repository.

## Project status

This repository was created as the GitHub home for the QuantEngine project. The current verified local successor build is **Phase 238**:

- Artifact: `QuantEngine_PHASE238_SUCCESSOR_WORKING_BUILD.zip`
- SHA-256: `cefc11275eff3d9eb37aee1ded24743bc5a6d2fbc69ee787e3fa2466d04e9e2a`
- Archive members: 2,481
- Archive integrity, manifest payload hashes, detached-record verification and reproducible second build: PASS
- Focused packaging/path and secret-scan tests: 46 passed; 18 subtests passed
- Python compileall: PASS
- Strict source manifest verification: PASS

**Important:** this initial commit is repository bootstrap documentation only. The complete Phase 238 source tree has not yet been transferred into this repository. No claim is made that the repository contains the application source or that GitHub Actions has passed.

## Safety / readiness

- NOT PRODUCTION READY.
- Live exchange writes are on HOLD; no live order was submitted in Phase 238.
- OOS readiness is not established.
- The full repository test suite is not certified green.
- Windows-native execution has not been locally verified; the Windows GitHub Actions job is intended to perform that verification once the source tree is committed.

## Local verification commands

```bash
python scripts/generate_manifest.py --root . --verify --strict
python -m compileall -q core scripts tests
python -m pytest tests/test_phase229_reproducible_packaging.py tests/test_phase231_release_candidate.py tests/test_phase232_detached_record_verification.py tests/test_phase233_strict_detached_record.py tests/test_phase234_archive_manifest_hashes.py tests/test_phase235_manifest_digest_record.py tests/test_phase237_windows_portable_paths.py tests/test_secret_scan_phase193b.py tests/test_secret_scan_phase0.py -q
```

Do not enable live trading based solely on these engineering checks.
