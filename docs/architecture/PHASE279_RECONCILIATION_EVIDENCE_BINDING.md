# Phase 279: reconciliation evidence identity and snapshot binding

## Objective

Bind lifecycle reconciliation decisions to the exact reserved order intent and to the complete observations used to make the decision. Reject explicit account or venue contradictions before journal mutation.

## Changes

- Venue-history matches reject explicit account or venue fields that contradict the requested scope.
- Venue-history evidence schema v2 binds the reservation payload digest, complete order snapshot, source, account, venue, timestamp, completeness assertion, and matched record.
- Delta reconciliation validates explicit account and venue scope in both snapshot metadata and the selected order/fill records.
- Delta evidence schema v2 binds the reservation payload digest and complete order/fill snapshots, including source and timestamps.
- Adversarial tests assert that scope mismatches leave the journal in DISPATCHING.

## Limitations

A digest detects byte-level changes to the evidence passed into the reconciler. It does not authenticate the venue, prove that an adapter used the correct account credentials, or prove provider-side completeness. The adapter must establish authenticated account scope, exhaustive pagination, retention coverage, and a trustworthy completeness assertion. Delta order and fill observations remain non-atomic; the configured maximum skew is not an exchange-atomic snapshot guarantee.

No network requests, credentials, live broker access, or live orders are used by these tests. Live order writing remains disarmed.
