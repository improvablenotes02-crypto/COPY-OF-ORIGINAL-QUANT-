# Phase 203 — Normalized market-data validation

## Scope

Adds venue-neutral, fixture-friendly validation primitives for normalized quotes and OHLCV bars. The implementation is deliberately independent of the live exchange clients and does not change order execution.

## Guarantees provided

- Requires a non-empty normalized symbol and source label.
- Requires timezone-aware timestamps and converts them to UTC.
- Requires finite positive prices; permits absent `last` when a bid/ask pair exists.
- Requires bid and ask together and rejects crossed quotes.
- Validates quote age, future timestamp tolerance, and expected symbol.
- Rejects duplicate normalized symbols in a quote batch.
- Checks OHLC consistency and finite non-negative volume.

## Important limits

These are local consistency checks, not proof that data is authentic, complete, exchange-synchronized, or suitable for a trading decision. The batch validator does not infer symbol aliases across venues. Source-specific session calendars, market holidays, quote sequence numbers, and instrument tick-size alignment require adapter-specific rules and have not been certified. No exchange API was called and no orders were submitted.

## Verification

Phase 203 tests use deterministic simulated fixtures only. Live execution remains on HOLD; prior frozen strategy-digest failures, incomplete full-suite verification, venue integrations for NSE/Sensex and forex, and credential rotation/revocation remain open.
