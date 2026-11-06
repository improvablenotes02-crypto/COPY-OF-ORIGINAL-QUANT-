# Phase 265 — Delta fill-history corroboration

## Read-only adapter

DeltaExchange.get_fill_history_snapshot(max_pages=100) reads authenticated
GET /v2/fills using the documented cursor pagination contract. It requests
page_size=50, follows meta.after until absent, and fails closed on malformed
responses, repeated cursors, authentication failure, or page-limit exhaustion.
The snapshot is a separate observation from order history and is not
exchange-atomic with it.

## Conservative aggregation

core.execution.delta_fill_reconciliation.summarize_delta_order_fills joins
fill records to exactly one order by venue order_id. It requires stable unique
fill identifiers, positive finite quantities, and consistent product scope
when product_id is present. Decimal arithmetic avoids binary float rounding.
An aggregate equal to order size is reported as FILLED corroboration; a
smaller positive aggregate is PARTIAL. An aggregate larger than order size,
duplicate fill identifier, missing fill identifier, or conflicting product
scope is rejected as unsafe evidence.

A zero-match result is NO_FILL_EVIDENCE only. It is never converted into
REJECTED, CANCELLED, or proof that submission did not occur. The helper does
not mutate the submission journal or trigger order resubmission.

## Account scope and limitations

The caller must supply an explicit account_id and source provenance. Delta
fill rows do not themselves contain an account identifier, so the account
scope is an adapter/operator assertion rather than independently verified
identity. The order-history and fills requests are sequential observations,
not a single atomic exchange snapshot. Callers must retain UNKNOWN whenever
the order/fill evidence is incomplete or inconsistent.

Official API reference: https://docs.delta.exchange/ (REST API: GET /fills;
cursor pagination; page_size limit 50).

## Safety

This phase adds authenticated GET-only functionality. It does not place,
edit, cancel, retry, or enable live orders. It does not certify live account
behavior or production readiness.
