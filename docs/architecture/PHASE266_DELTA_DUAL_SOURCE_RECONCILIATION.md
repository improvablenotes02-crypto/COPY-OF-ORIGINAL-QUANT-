# Phase 266 — Delta dual-source submission reconciliation

## Scope

Phase 266 adds a deterministic reconciliation function that consumes the
Phase 264 order-history snapshot and Phase 265 fills snapshot. It performs no
network I/O and never submits, retries, edits, or cancels an order. The
function transitions the durable submission journal only after both evidence
sets pass validation and agree.

## Evidence requirements

- Both snapshots must identify venue `delta`, have non-empty source
  provenance, be marked complete, and carry valid local observation timestamps.
- Both observations must be fresh (30 seconds by default) and within 15 seconds
  of each other by default. They are not exchange-atomic.
- One and only one order must match the exact client order ID.
- Fill rows must match the exact venue order ID; stable unique fill IDs,
  positive quantities, and product consistency are enforced by Phase 265.
- The caller must supply an explicit account scope. Delta fill records do not
  independently authenticate or identify that account, so this remains a
  caller/adapter assertion.

## Resolution policy

- Open/working order with no fill evidence may resolve to ACKNOWLEDGED.
- Explicit rejected order with no fill evidence may resolve to REJECTED.
- Positive partial/full fills may resolve to PARTIAL/FILLED when consistent
  with the order record's cumulative filled quantity and lifecycle status.
- A cancellation/expiry after a corroborated partial fill retains the
  cancellation/expiry lifecycle state while including fill quantity evidence.
- A filled/partial order without fill corroboration remains UNKNOWN.
- Rejected order plus fills, order/fill quantity disagreement, duplicate
  order matches, missing order, incomplete/stale/skewed snapshots, or
  cancelled/expired order without fill evidence remain unresolved.
- Missing fills are never interpreted as proof of rejection or proof that an
  order was never submitted. Unresolved cases do not mutate the journal.

## Limitations

Snapshot completeness is a pagination assertion, not a guarantee that the
exchange exposed all events at the same instant. Account identity is supplied
by the caller. A delayed fill-history endpoint may cause a safe unresolved
result. Operators must reconcile again with fresh evidence or use an
independent venue/account statement before taking action.

## Safety

This is read-only evidence processing. Live order writing remains governed by
existing independent safety gates and is not enabled by this phase. The work
does not establish production readiness or guarantee exactly-once exchange
execution.
