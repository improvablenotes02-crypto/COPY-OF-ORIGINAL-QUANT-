# Next Actions — QuantEngine

## Verified on the current continuation branch

- **Cross-platform release archive proof:** Phases 239–241 verified the exact release candidate on Ubuntu and Windows, including deterministic build, archive integrity, portable paths, extraction payload hashes, and detached-record verification.
- **Adversarial archive checks:** Phase 240 added rejection tests for symlink/special-file metadata, directory entries, encrypted members, duplicate names, and file/directory path collisions.
- **Detached-record integrity:** Phase 241 enforces a bounded, canonical record format while retaining compatibility with the earlier record format.
- **Credential rotation hardening:** Phase 242 removes old managed Delta variables even when written with a dotenv `export` prefix. The dedicated credential setup test passed on Ubuntu; the Windows runtime workflow is still completing its remaining regression steps.

## Remaining work, in priority order

1. **Owner Sandbox verification:** Run `python scripts/configure_delta_credentials.py` locally, select the correct region and Sandbox, then run `python scripts/check_delta_credentials.py`. Keep API keys and secrets on the operator's machine; never send them through chat or GitHub.
2. **Market-data evidence:** Complete and independently verify the documented multi-day L2 capture. Keep continuity claims partial until primary capture evidence is available.
3. **External reconciliation:** Complete the external tax-invoice reconciliation from primary source records; do not infer missing evidence.
4. **Independent strategy validation:** Establish out-of-sample evidence for any claimed trading edge. Passing software tests does not establish profitability.
5. **Release governance:** Resolve the pull request's reported mergeability state, review the complete diff, and complete the full regression/release checklist before considering a release.

## Mandatory posture

- `NOT_PRODUCTION_READY`
- `EDGE NOT ESTABLISHED`
- Release gate: `HOLD`
- Exchange order writing remains disarmed by default.
- No live trading or production deployment is authorized by these engineering changes.
