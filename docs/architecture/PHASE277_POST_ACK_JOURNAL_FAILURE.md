# Phase 277 — Post-Acknowledgement Journal Failure Safety

## Objective

Exercise the execution boundary where the fake venue returns an accepted
working-order acknowledgement, but persisting ACKNOWLEDGED in the local
submission journal fails.

## Failure scenario

The executor has already durably written PREPARED and DISPATCHING and the
transport returns an accepted response. The journal's next transition is
then forced to raise a controlled SubmissionJournalError. This models a
journal write failure after a venue response, without contacting a real venue.

## Required invariants

- The journal remains DISPATCHING when ACKNOWLEDGED cannot be committed.
- DISPATCHING remains visible in the unresolved inventory.
- The failure propagates to the caller; it is not swallowed or rewritten as
  a successful local acknowledgement.
- A fresh executor and journal cannot reserve the same client order ID again.
- A retry attempt is rejected before the fake transport is called.
- No automatic resend or inferred acknowledgement is performed.

## Test strategy

The test uses the existing Delta executor boundary, an offline fake exchange,
a test-only safety token, and a temporary SQLite journal. The fake exchange
returns a deterministic working-order response and records every call. The
journal transition wrapper fails only for ACKNOWLEDGED, allowing PREPARED and
DISPATCHING to commit normally. A fresh executor then attempts the same ID
and must be rejected without a second fake transport call.

## Safety and limitations

No broker credentials, network requests, live orders, or production safety
tokens are used. The test demonstrates local fail-closed behavior for a
post-response journal failure; it does not prove venue-side order status or
network exactly-once delivery. The unresolved DISPATCHING row still requires
authoritative venue-history reconciliation.

Live order writing remains disarmed.

## Validation

```bash
python -m pytest tests/test_order_executor_phase277.py -q
python scripts/generate_manifest.py --root . --verify --strict
```
