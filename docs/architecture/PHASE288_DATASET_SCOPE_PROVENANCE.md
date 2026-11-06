# Phase 288 — Dataset scope provenance and backtest isolation

Status: additive contract and adversarial tests committed. CI and strict-manifest
certification are pending until the final phase commit is checked.

## Why this is separate

The Phase 17 dataset manifest is frozen and remains unchanged. Phase 288 adds
an independent scope envelope rather than changing its canonical fields or
invalidating existing research artifacts.

## Required provenance

Each record binds:
- venue, region, and environment (INDIA/GLOBAL, SANDBOX/PRODUCTION);
- instrument, symbol, and timeframe;
- public-market versus private-account classification;
- source and source timestamp;
- schema and normalization versions;
- lowercase SHA-256 dataset digest and row count;
- completeness plus explicit pagination-exhaustion evidence.

Private account datasets additionally require tenant ID, internal account ID,
and provider account ID. Public market datasets must not carry a private
account identity.

## Backtest admission

The validate_backtest_inputs function rejects empty input, missing/untyped
records, partial or unknown datasets, incompatible venue/region/environment
scopes, public/private mixing, and private account identity mismatches.
Complete datasets must explicitly prove pagination exhaustion.

## Limits and safety

This is an admission/consistency contract, not proof that a venue actually
produced the data. A SHA-256 digest establishes byte identity only; it does
not establish authenticity, correctness, exchange atomicity, or source
completeness. Source adapters must populate this envelope from authenticated
configuration and actual retrieval responses, not user-editable labels.

The validator is not yet wired into every historical research/backtest entry
point. This phase therefore does not certify all backtests, account data, or
production trading. Live order writing remains disarmed; no credentials or
orders are introduced.
