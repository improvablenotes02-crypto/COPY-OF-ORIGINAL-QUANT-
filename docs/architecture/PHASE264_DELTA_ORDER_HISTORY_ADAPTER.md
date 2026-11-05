# Phase 264 — Delta Exchange order-history adapter

## Implemented surface
`DeltaExchange.get_order_history_snapshot(max_pages=100)` is a read-only,
authenticated adapter over the documented Delta v2 endpoints:

- `GET /v2/orders?state=open&page_size=50` for active orders.
- `GET /v2/orders/history?page_size=50` for cancelled and closed orders.

Both endpoints are read page-by-page using Delta's `meta.after` cursor. The
adapter stops only when the cursor is absent. It refuses malformed responses,
repeated cursors, unauthenticated access, and page-limit exhaustion; it never
returns a truncated page sequence as complete. The documented maximum history
page size of 50 is used.

## Evidence and limitations
The returned object includes the combined records, source identifier, local
observation timestamp, pagination counts, and an explicit
`observation_is_exchange_atomic=false` marker. The two endpoints are read
sequentially, not as one exchange-atomic snapshot. Concurrent order transitions
can therefore produce duplicate or temporarily absent records; duplicate
client-order-ID matches fail closed in Phase 263, and absence remains unresolved.

Delta's public API reference documents the active-order endpoint, the
cancelled/closed order-history endpoint, cursor pagination, and the page-size
limit. It does not establish a single atomic cross-endpoint snapshot or prove
every rejection/fill edge case for every account configuration. Operators must
retain UNKNOWN when evidence is incomplete. Use fills history as additional
corroboration where required; this adapter does not infer rejection from absence.

Official references:
- https://docs.delta.exchange/#get-order-history-cancelled-and-closed
- https://docs.delta.exchange/#get-active-orders
- https://community.delta.exchange/t/api-update-changes-to-history-endpoints-and-parameter-clarifications/2261

## Safety
This adapter only performs authenticated GET requests. It adds no place, edit,
cancel, retry, or live-order-write path. The read-only history adapter is not
proof of a live broker deployment and does not enable live execution.
