# Phase 281: exact account identity in venue-history evidence

## Objective

Prevent a venue-history record from being treated as belonging to the requested account when its explicit account identifier differs only by letter case.

## Changes

- Compare explicit account identifiers exactly after trimming surrounding whitespace.
- Continue normalizing venue names case-insensitively because venue labels are canonical names rather than account identifiers.
- Cover snake_case and camelCase account fields.
- Verify mismatched account/venue evidence leaves the submission journal in DISPATCHING and valid matching evidence can resolve it.

## Safety and limitations

This check prevents accidental cross-account evidence acceptance at the reconciliation boundary. It does not authenticate the account that fetched the snapshot; that remains the responsibility of a controlled credential-owning adapter. No network calls, credentials, or live orders are used. Live order writing remains disarmed.
