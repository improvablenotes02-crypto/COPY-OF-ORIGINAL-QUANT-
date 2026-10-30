# Phase 230 — Cross-platform release assurance

## Change

The process-cleanup workflow now includes a dedicated release-package reproducibility job on both `ubuntu-latest` and `windows-latest`. Each runner verifies the checked-in source manifest and runs the focused Phase 229 packaging tests. The tests build fixture archives twice, confirm byte-for-byte identity despite source mtime changes, check ZIP metadata normalization and archive integrity, ensure `.env` and `.git` are excluded, and verify that a source-content change alters the archive hash.

## Local validation boundary

This development host can execute the POSIX-side checks only. Adding a Windows CI job is not evidence that the hosted Windows job has passed; inspect the actual GitHub Actions run before marking Windows verified. This phase does not certify the full repository test suite, strategy performance, broker connectivity, or live trading.

## Reproduction

```bash
python scripts/generate_manifest.py --root . --verify --strict
python -m pytest tests/test_phase229_reproducible_packaging.py -q
python -m compileall -q core scripts tests
python scripts/generate_manifest.py --root . --verify --strict
```
