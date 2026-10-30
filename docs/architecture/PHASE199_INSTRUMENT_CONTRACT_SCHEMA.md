# Phase 199 — normalized instrument contract schema

## Scope

Phase 199 adds a venue-neutral `InstrumentSpec` validator for normalized contract metadata. It is a data-quality boundary, not a broker/exchange adapter, market-data feed, strategy, or execution authorization. Existing order paths are not wired to this schema in this phase.

## Validated fields

- All instruments: non-empty symbol/family/type; finite positive tick size, quantity step, and contract multiplier.
- Options: explicit underlying, call/put right, positive strike, canonical ISO calendar expiry, and positive integer lot size.
- Forex: normalized `BASE/QUOTE` symbol using three-letter uppercase currency codes; optional currency metadata is three characters.
- Decimal metadata is normalized to `Decimal` to avoid binary floating-point comparisons in contract increments.

## Important limits

- A syntactically valid contract is not proof the contract exists, is current, or is tradable at a venue.
- Expiry is a calendar date, not a settlement timestamp; venue timezone, expiry cutoff, holiday calendar, option lot/tick rules, FX pip conventions, contract multiplier, margin, and order constraints must come from verified venue metadata.
- No NSE/Sensex or forex adapter is implemented or certified by this change. NSE index options and FX pairs in tests are synthetic validation fixtures.
- Live execution remains HOLD. This module grants no write authority. Frozen strategy digest failures remain open; the full suite remains incomplete; no edge is proven; credential revocation remains unverified.
