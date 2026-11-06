# Phase 280: strict Delta pagination-exhaustion evidence

## Objective

Do not mark a Delta order or fill history snapshot complete unless the provider returns a structurally valid success response with an explicit pagination metadata object and an explicit `after` cursor value on every page.

## Changes

- Require `success is True`; absent success flags are not accepted.
- Require a mapping-valued `meta` object containing the `after` key on every page.
- Treat only an explicit null `after` as cursor exhaustion.
- Reject blank, whitespace-only, and non-string continuation cursors.
- Preserve cursor-cycle and maximum-page fail-closed checks.
- Include per-stream cursor-exhaustion, cursor-hop, and record-count evidence in the returned order/fill snapshots.
- Add offline adversarial tests for missing metadata, missing cursor keys, malformed cursors, and missing success flags.

## Provider contract

Delta's current REST documentation describes cursor pagination through `meta.after`; null indicates there is no subsequent page. The history endpoints no longer expose a total count, so the adapter must follow the cursor chain until the provider explicitly terminates it. These local fields attest to the adapter's observed pagination behavior; they do not prove an exchange-atomic snapshot or guarantee that the provider's underlying dataset is complete.

## Safety

The tests use only fake REST responses. They make no network requests and perform no order writes. Live order writing remains disarmed.
