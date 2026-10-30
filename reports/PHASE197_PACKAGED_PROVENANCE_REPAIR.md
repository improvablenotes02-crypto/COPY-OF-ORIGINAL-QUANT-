# Phase 197 — Packaged Strategy Provenance Repair

Date: 2026-10-24  
Disposition: **HOLD — NOT PRODUCTION READY**

## Change delivered

The release tree now carries `reports/strategy_provenance_bundle.json`, a minimal source-derived record for the three historical Git milestones used by strategy reconstruction. It records full commit IDs, tree IDs, per-file Git blob object IDs, raw and LF-normalized SHA-256 digests, and the nine-file composite digests. It does not contain Git objects, source credentials, or the complete `.git` directory.

`core/research/historical_reconstruction.py` now uses this bundle only when Git blob retrieval is unavailable and only when the bundle has the expected schema, exact ordered file list, and a matching full/short commit identifier. Direct Git reconstruction remains preferred when `.git` is present. The report explicitly identifies bundle-backed results as `packaged_unsigned_source_derived_bundle`; the bundle is **unsigned archival evidence**, not an independent digital signature.

The historical test pin `c52e648ca24fb03b9ba818ebb766e32b035b48df201d5a2a1b254d04f7f3d5a6` is still labeled `UNRECONSTRUCTED_FROM_AVAILABLE_BLOBS`. No hash pin or legacy assertion was changed to force a green result.

## Verification

- Historical reconstruction + identity separation + Phase 197 bundle tests: **11 passed**; snapshot guard reports pristine tree, no restores, no test-added files.
- Focused execution safety / authorization suite: **191 passed, 2 skipped, 27 subtests passed**; snapshot guard reports pristine tree, no restores, no test-added files.
- Secret scan: **PASS**.
- Manifest verification: **PASS (0 problems)**.
- Python compile check (`compileall` for `core`, `backtesting`, and `tests`): **PASS**.
- Broader strategy/OOS selection: **87 passed, 4 failed**. The four failures are frozen nine-file digest assertions comparing current raw digest `9c56f3ff7dea2a3ea98adf226aff775d263ebfcf1bbb2697ca244ab6cd54f35a` with the historical pin. Those assertions were not changed.
- Full test suite: **NOT COMPLETE**; no full-suite pass is claimed.
- Exchange order writes: none submitted during this work.

## Security and release limitations

- The original Phase 161 archive had populated `.env` credentials. Treat those credentials as exposed; exchange-side rotation/revocation is operator action and has not been verified here.
- The package excludes `.env` and `.git`. The provenance bundle contains hashes and commit identifiers only; because it is unsigned, recipients should verify it against the original archive or a trusted independently retained source before treating it as authenticated provenance.
- No profitability edge or production readiness is established. B-08 remains uncalibrated and B-09 blocked in prior project records.
- This remains a Python/Delta Exchange crypto engine, not the separate requested standalone Android app with Flattrade and Nifty/Sensex/forex functionality.

## Decision

**HOLD. Keep live trading disabled.** Phase 197 repairs packaged-history reconstruction and documents provenance more accurately; it does not resolve the historical raw strategy-pin mismatch, complete the full suite, or certify live trading.
