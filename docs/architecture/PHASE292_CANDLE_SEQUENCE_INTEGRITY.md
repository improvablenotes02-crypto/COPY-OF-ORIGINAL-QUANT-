# Phase 292 — Candle Sequence Integrity

## Contract

The Phase 291 canonical candle hash now rejects a replay sequence unless candle timestamps are strictly increasing. Duplicate timestamps and descending/out-of-order rows fail closed before replay.

The check intentionally does not require fixed timestamp spacing. Market sessions, exchange halts, missing upstream bars, and trading calendars can create legitimate gaps; completeness is still represented separately by dataset provenance and must not be inferred from timestamp spacing alone.

## Verification

The phase test suite covers duplicate timestamps, descending and locally out-of-order sequences, pre-replay rejection, and irregular-but-increasing timestamps. The runtime CI workflow includes the new test file.

## Scope

This protects replay ordering and prevents ambiguous duplicate bars. It does not independently prove that no bars are missing, authenticate the exchange source, or authorize live execution.
