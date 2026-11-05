# Phase 278 — Evidence-bound UNKNOWN lifecycle transitions

## Objective

Prevent a caller from resolving an ambiguous submission directly through the
SQLite journal without attaching a well-formed evidence digest. The journal is
the final lifecycle boundary; higher-level reconciliation checks alone are
insufficient if other internal callers can invoke `transition()` directly.

## Implementation

- `SQLiteOrderSubmissionJournal.transition()` now requires a lowercase,
  64-character SHA-256 digest when the persisted state is `UNKNOWN` and the
  requested target is a resolved state.
- The digest is retained in the transition detail for audit and incident review.
- Venue-history and Delta dual-source reconciliation pass the digest they
  already compute from their evidence snapshots.
- The Phase 273 health-report fixture now uses an ordinary dispatch-to-reject
  lifecycle instead of bypassing reconciliation from `UNKNOWN`.
- Focused tests prove that missing/malformed digests leave the row unresolved,
  and a valid digest is persisted with the resolution.

## Security interpretation and limits

A digest is a content fingerprint and provenance reference. It does **not**
authenticate the venue, prove that a caller's evidence is complete, or replace
adapter-level validation of account scope, freshness, completeness, status,
and fill consistency. The journal does not fetch venue data and never resends
orders. A digest supplied by an untrusted caller is not a trust anchor.

## Certification boundary

This phase is scoped to journal lifecycle transitions and the two existing
reconciliation paths. Exact-commit CI must pass on Ubuntu and Windows with the
strict source manifest. Live order writing remains disarmed; no real broker
credentials, network requests, or orders are used by these tests.
