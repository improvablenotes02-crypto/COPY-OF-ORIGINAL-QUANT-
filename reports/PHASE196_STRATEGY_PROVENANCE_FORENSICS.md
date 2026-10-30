# Phase 196 — Strategy Provenance Forensics

Date: 2026-10-24  
Disposition: **HOLD — NOT PRODUCTION READY**

## Objective

Continue the Phase 195 work by documenting the unresolved strategy-identity mismatch without changing frozen historical hash pins, weakening assertions, or claiming a test suite passed when it did not.

## Findings

1. The historical test pin remains `c52e648ca24fb03b9ba818ebb766e32b035b48df201d5a2a1b254d04f7f3d5a6`. Existing project records describe it as a pre-commit Windows working-tree digest with CRLF line endings. The exact original working-tree snapshot is not present as a verified, reproducible artifact in this successor package.
2. The nine-file LF-normalized composite at the Phase 14 baseline commit `3f19895` is `db5bcdc01cd88b6c997e630e7ad1f6879f72f4ccc191393a6ff41675df52be72`.
3. The nine-file LF-normalized composite at runtime-boundary commit `fbeb860` and historical `HEAD` `ffefa14` is `9eff61b777846c7f5e2056c486c9c381872a93e154d35160e70f63051c8fd8a2`.
4. The current release tree's nine-file LF-normalized composite is `ba17582d0ab96913f81d0e6ac652368e609bb28f22a24200f53bf9b6cd60ded5`; its raw-byte composite recorded during Phase 195 was `9c56f3ff7dea2a3ea98adf226aff775d263ebfcf1bbb2697ca244ab6cd54f35a`.
5. Three source files were identical to the Phase 14 baseline in the prior Git-backed comparison: `core/execution/entry_model.py`, `core/execution/execution_engine.py`, and `core/setup/trade_setup_builder.py`. Six were modified: `config/risk_settings.py`, `core/backtesting/accounting.py`, `backtesting/backtester.py`, `core/paper_trading/paper_trading_engine.py`, `core/risk/risk_engine.py`, and `core/setup/decision_engine.py`.
6. The successor archive intentionally omits `.git`. As a result, `core/research/historical_reconstruction.py` cannot reconstruct Git milestones when run from this packaged tree; it reports missing milestone blobs and cannot independently prove the three-versus-six file reconciliation from the release archive alone. This is a packaging/provenance limitation, not proof that the historical pins are wrong.

## Verification recorded

- Phase 195 focused safety/authorization suite: **191 passed, 2 skipped, 27 subtests passed**.
- Focused strategy/history suite: **85 passed, 6 failed**. The failures are expected blockers in frozen digest assertions and Git-backed reconstruction when `.git` is absent; they have not been suppressed or re-pinned.
- Full test suite: **INCOMPLETE**. The previous run hit the execution time limit after roughly 20 minutes. No full-suite pass is claimed.
- No exchange order writes were submitted during this work.

## Safe resolution path

1. Preserve the original pins and tests unchanged.
2. Recover an authenticated historical snapshot or independently signed provenance bundle that includes the exact nine source files, canonicalization rules, source commit identifiers, and expected digests. Do not infer the missing CRLF working tree from the current files.
3. Decide and document whether the distributable should include a minimal, non-sensitive provenance bundle (preferred over shipping the entire `.git` history). Add tests that verify the bundle's signatures/hashes and ensure reconstruction behaves explicitly when provenance is unavailable.
4. Only after operator review, create a new versioned strategy identity for any intentional post-baseline strategy changes; retain the old identity as historical evidence.
5. Run the complete test suite in an environment with sufficient execution time, then perform independent risk, privacy, security, paper-trading, and venue integration gates.

## Security and release blockers

- The original Phase 161 archive contained populated `.env` credentials. Treat those credentials as exposed and rotate/revoke them through the exchange; revocation has not been verified here.
- The successor archive excludes `.env` and `.git`; `.env.example` remains for configuration guidance.
- Profitability / out-of-sample edge is not established. B-08 remains uncalibrated and B-09 blocked according to prior project evidence.
- This codebase is a Python/Delta Exchange crypto engine, not the requested standalone Android/Flattrade Nifty/Sensex/forex app. It does not satisfy that separate product requirement.

## Release decision

**HOLD. Do not enable live trading or treat this archive as production-ready.** Phase 196 adds provenance clarity only; it does not claim to resolve the historical identity discrepancy or the incomplete full-suite gate.
