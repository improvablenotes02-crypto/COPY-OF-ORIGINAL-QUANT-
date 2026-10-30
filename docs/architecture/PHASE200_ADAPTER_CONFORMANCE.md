# Phase 200 — Shared adapter conformance boundary

## Scope

Phase 200 adds `core.exchanges.adapter_conformance`, a venue-neutral structural
validator for market adapters. All adapters must expose callable product,
balance, and position reads. An adapter that declares live order support must
also expose callable place, cancel, and order-status methods.

The validator does **not** invoke these methods. It does not establish that a
broker API is reachable, that the remote request/response schema is correct,
that prices/quantities are rounded safely, or that order writes are authorized.
A successful result is structural conformance only.

## Fail-closed gates

- Read-method omissions fail conformance.
- Declaring `live_orders=True` without the full order method surface fails.
- Method presence does not grant live eligibility; `MarketCapabilities` still
  requires the explicit live-order declaration, verification flag, and evidence
  reference.
- Venue evidence and the structural check are independent requirements.
- Existing venue adapters and execution pathways are not automatically upgraded
  or authorized by this addition.

## Verification

`tests/test_phase200_adapter_conformance.py` covers read-only shape, missing
methods, incomplete order shape, and the distinction between structural
conformance and live execution eligibility.

## Current status / limitations

QuantEngine remains a Delta-focused crypto implementation. NSE/Sensex and forex
adapters remain unimplemented and uncertified. The broader suite is not claimed
as passing: the previously reported four frozen strategy digest failures remain
open, and a full-suite run remains incomplete. Live execution stays on HOLD.
No exchange orders were submitted. Rotation/revocation of credentials exposed in
the original archive remains an operator action and is not verified here.
