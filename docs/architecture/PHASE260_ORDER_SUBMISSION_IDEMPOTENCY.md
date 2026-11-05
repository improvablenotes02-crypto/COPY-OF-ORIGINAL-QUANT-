# Phase 260 — order submission idempotency boundary

## Change

`DeltaOrderExecutor` now atomically reserves each validated
`client_order_id` immediately before the exchange transport call.
A second submission using the same ID is refused locally before any
second transport write.

The reservation is deliberately retained if the transport raises or the
acknowledgement is ambiguous. A timeout does not prove that the exchange
did not accept the order. Automatically clearing the reservation and
retrying could create duplicate exposure.

## Regression coverage

`tests/test_order_executor.py` verifies:

- a repeated submission with the same client order ID makes exactly one
  exchange write;
- when a fake transport records acceptance and then raises a timeout,
  a retry with the same client order ID is refused and does not write again.

The executor uses a lock around the check-and-reserve operation, protecting
multiple threads sharing one executor instance.

## Operational recovery

A duplicate refusal is not permission to generate a new client ID and retry.
The original ID must first be reconciled against authoritative venue order
and fill records. If the venue query is unavailable, incomplete, or
contradictory, new execution must remain blocked.

## Explicit limits

This guard is process-local and scoped to one executor instance. It does
not provide durable idempotency across process restarts, multiple executor
instances, hosts, or independent clients. Cross-restart safety still
depends on the persistent execution journal and authoritative exchange
reconciliation. The fallback client-ID counter is also process-scoped;
production routing must use registry-minted stable order identities.

No venue-specific guarantee that `client_order_id` is an exchange-enforced
idempotency key is inferred by this change. That behavior requires current
venue documentation and sandbox evidence.

Live order writing remains disarmed. This is a local duplicate-write
barrier, not production execution certification. Overall status remains
`NOT_PRODUCTION_READY / HOLD`.
