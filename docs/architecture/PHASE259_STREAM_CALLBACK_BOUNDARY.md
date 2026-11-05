# Phase 259 — Stream callback lifecycle boundary

## Change

`SubscriptionWorker._on_candle` now accepts callbacks only while the
subscription state is `LIVE` or `STALE`. Callbacks arriving while
`CONNECTING`, `RECONNECTING`, `STOPPED`, or `FAILED`
are discarded before they can update stream-health timestamps, counters,
candle-deduplication state, or downstream strategy callbacks.

This protects against an asynchronous transport race: a callback may already
be queued when a disconnect or unsubscribe occurs. Calling `unsubscribe`
is necessary but is not proof that all previously queued callbacks have been
cancelled.

## Regression coverage

`tests/test_realtime.py` now exercises two deterministic cases:

- A callback captured before disconnect is invoked while the worker is
  `RECONNECTING`; it must not be delivered or mutate received counters.
  After a successful reconnect, a fresh callback is accepted.
- A callback captured before stop is invoked after the worker reaches
  `STOPPED`; it must not mutate the retired worker or reach strategy code.

Run locally:

```bash
python -m pytest -q tests/test_realtime.py
```

## Scope and remaining limits

This is a local callback admission guard, not proof of end-to-end exchange
recovery. It does not implement a production websocket supervisor, guarantee
exchange sequence continuity, or replace historical gap repair and order
reconciliation. The verified Delta socket transport remains evidence-gated
and is not yet production-wired across all target venues.

Live order writing remains disarmed. Overall release status remains
`NOT_PRODUCTION_READY / HOLD` until venue-specific feed evidence,
restart/reconciliation tests, execution-boundary certification, and the
full regression suite are complete.
