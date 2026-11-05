# Phase 282: authenticated Delta account identity binding

## Objective

Ensure Delta order-history and fill-history snapshots carry the identity returned by the authenticated API principal, rather than relying solely on a caller-supplied account label.

## Provider contract

Delta documents GET /v2/users/trading_preferences as an authenticated account-level endpoint. Its successful response contains result.user_id (documented as an integer). The adapter now requires an explicit success: true, an object result, and a positive non-boolean integer user_id. The resulting snapshot records that ID as a decimal string in account_id and records the endpoint in account_id_source.

## Changes

- Resolve the authenticated principal before reading either order history or fills.
- Fail closed on unsuccessful responses, malformed result objects, missing IDs, booleans, non-integers, and non-positive IDs.
- Attach the provider-derived account ID and provenance to both independent snapshots.
- Existing reconciliation scope validation compares these explicit IDs against the caller's expected account ID; callers must now supply the exact provider user ID for this API principal.
- Add offline adversarial tests for valid identity, malformed/failed identity responses, and authentication gating.

## Limitations

This binds snapshots to the identity returned by Delta's authenticated preferences endpoint. It does not prove that order/fill history pagination covers all provider records, that the two snapshots are exchange-atomic, or that a user ID represents every possible subaccount context. If a deployment uses a parent key to query another account's records through a separate subaccount mechanism, it must obtain and bind that target account's provider identity explicitly; it must not relabel the authenticated principal as the target account.

Tests use fake REST responses only. No credentials, network requests, or live order writes are introduced. Live order writing remains disarmed.

## References

- Delta Exchange REST API documentation: GET /v2/users/trading_preferences and its authenticated result.user_id response.
