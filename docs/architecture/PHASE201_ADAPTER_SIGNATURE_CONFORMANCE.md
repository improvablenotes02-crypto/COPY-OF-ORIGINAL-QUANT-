# Phase 201 — Adapter signature conformance

## Scope

Phase 201 extends the Phase 200 adapter structural validator to check that required methods can accept the minimum positional arguments expected by the shared interface. Read methods are checked with zero required positional arguments; declared order methods are checked with one argument. Optional extra parameters remain allowed.

## What this proves

- Required adapter methods exist and are callable.
- Their Python signatures can accept the minimum contract call shape.
- A method that exists by name but cannot accept the expected call is rejected.

## What this does not prove

This is not a runtime/API certification. It does not verify returned schemas, network connectivity, authentication, idempotency, rate limits, venue-specific order rules, fill behavior, or financial correctness. A passing adapter must not be treated as live-trading authorization. Existing market coverage remains Delta-focused; no certified NSE/Sensex or forex adapter is introduced here.

## Release posture

Live trading remains HOLD. No exchange orders are submitted by these tests. Full-suite status remains incomplete, and previously recorded frozen strategy-digest failures remain open. Credential revocation for the originally exposed credentials has not been verified and remains an operator action.
