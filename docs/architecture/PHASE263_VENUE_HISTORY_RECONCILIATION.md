# Phase 263 — Evidence-gated venue order-history reconciliation

## Scope
Phase 262 blocks new live routing while PREPARED, DISPATCHING, or UNKNOWN
submission journal rows remain unresolved. Phase 263 adds a pure reconciliation
adapter that consumes a caller-supplied venue order-history snapshot.

## Safety contract
- Match only by the stable client order ID; zero matches remain unresolved.
- Duplicate matches, malformed records, incomplete history, stale snapshots,
  future timestamps, and unknown status labels fail closed.
- An absent order is **not** evidence of rejection. Delayed indexing, retention,
  and endpoint coverage differ across venues.
- Open/accepted, filled, partial, rejected, cancelled, and expired states are
  classified through the existing conservative acknowledgement classifier.
- The journal stores venue/account/source provenance, snapshot timestamp, raw
  status label, and a SHA-256 digest of the matched record.
- No network calls, order writes, retries, cancels, or automatic operator
  resolutions are performed.

## Adapter requirements
A venue adapter may set `complete=True` only when its documented endpoint
covers the relevant order lifecycle, including completed and rejected orders,
not merely currently open orders. It must provide a trustworthy snapshot
timestamp and stable account/venue identity. If the broker API does not expose
such history, the adapter must not fabricate completeness; the submission
remains blocked for explicit manual reconciliation.

## Limitations
This is an adapter contract and deterministic local reconciliation layer, not
a verified integration with any specific broker. Each venue requires official
API documentation review and sandbox evidence before production use.
Live order writing remains disarmed.
