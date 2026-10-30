# Phase 198 — Multi-market adapter readiness

**Status: architecture groundwork only; no additional market is certified for live trading.**

## User target

QuantEngine is a separate project intended to cover crypto, NSE, Sensex and forex. It is not the separate Android/Flattrade app project. The current distributable remains a Python engine whose concrete exchange integration is Delta Exchange-focused.

## Source inventory finding

- `core/exchanges/base_exchange.py` currently defines generic product, balance, position and order methods, but does not encode instrument/session/data-feed capabilities.
- `core/exchanges/base_contract.py` has some option metadata fields, but venue-specific order verification is still opt-in and fail-closed.
- `core/exchanges/exchange_registry.py` registers arbitrary exchange instances; registration does not certify that an adapter implements market-data, contract, order, cancellation, or reconciliation semantics for a particular venue.
- No claim is made here that NSE cash, NSE index derivatives (including Sensex products), or a spot-FX broker adapter is implemented or certified.

## Phase 198 change

Added `core/exchanges/market_capabilities.py`, a small declarative metadata model for market family, instrument type, market-data/history/paper capabilities, and explicit live-write verification. It is not wired to the order executor and cannot place orders. Live eligibility is false by default and requires all of: `live_orders`, `live_execution_verified`, and a non-empty evidence reference. Marking verification true without an evidence reference raises `ValueError`.

## Required adapter sequence

1. **Crypto:** keep Delta as the existing concrete adapter; separately validate product metadata, public feed freshness, authenticated preflight, order lifecycle, and reconciliation against current venue evidence.
2. **NSE/Sensex:** select and implement a supported Indian broker adapter. Model cash, futures, index options, expiry, strike, option type, lot size, tick size, market sessions, circuit/price bands, and exchange/broker order IDs. Do not reuse crypto sizing or order payload assumptions.
3. **Forex:** choose the intended broker/venue and whether this means spot FX, CFDs, or exchange-traded currency derivatives; model pip/tick, contract size, trading sessions, financing/swap and jurisdictional restrictions before enabling execution.
4. **Shared core:** normalize timestamps and quotes at adapter boundaries; maintain instrument-specific risk sizing; keep market-data authority separate from order-write authority; require broker/exchange reconciliation and kill-switch tests per adapter.
5. **Evidence:** each adapter needs recorded contract tests and test-environment evidence before live execution can be eligible. An enum or config flag alone is not proof.

## Validation

`tests/test_phase198_market_capabilities.py` tests default-deny behavior, evidence requirements, and market/instrument matching. These tests validate metadata only; they do not certify a venue or prove profitability.

## Release gates still open

- Four frozen strategy-digest failures remain from Phase 197's broader strategy/OOS selection.
- The full test suite has not completed successfully in the recorded run.
- No profitability edge is established by this capability model.
- Live trading remains on HOLD; no exchange order writes were performed for this phase.
- Previously exposed credentials must be rotated/revoked by the operator; revocation is not verified.
