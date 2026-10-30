# Phase 202 — Read-only adapter behavioral probes

## Scope

Phase 202 adds an opt-in smoke probe for a deliberately supplied exchange adapter. It invokes `get_products`, `get_balance`, and `get_positions` at most once each and validates only broad return shapes. It never invokes `place_order`, `cancel_order`, or any other write operation.

## Failure behavior

Missing methods, unexpected return shapes, and exceptions fail the probe. Exception messages and returned payloads are not copied into the report, reducing the risk of leaking secrets or large private responses. The probe continues across independent read methods so one failure does not hide other shape defects.

## Limitations

A passing probe is not proof that the data are accurate, fresh, complete, correctly normalized, or safe to trade. The probe may perform read-only API calls if the supplied adapter is connected to a live venue, so operators should run it only in an approved environment. It does not authorize live orders and does not change the release HOLD. NSE/Sensex and forex adapters remain unimplemented/certified in this release.
