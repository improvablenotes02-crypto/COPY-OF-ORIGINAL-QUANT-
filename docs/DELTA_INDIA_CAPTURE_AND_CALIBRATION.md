# Delta India: read-only capture and passive-fill calibration plan

Status: preparation only. This document does not authorize order placement.

## Canonical venue and environment separation

QuantEngine's venue registry defines the following Delta India endpoints:

| Purpose | Endpoint |
|---|---|
| Production REST | `https://api.india.delta.exchange` |
| Production public WebSocket | `wss://public-socket.india.delta.exchange` |
| Production private WebSocket | `wss://socket.india.delta.exchange` |
| India sandbox REST | `https://cdn-ind.testnet.deltaex.org` |
| India sandbox public WebSocket | `wss://socket-ind-pub.testnet.deltaex.org` |
| India sandbox private WebSocket | `wss://socket-ind.testnet.deltaex.org` |

Production public market-data capture uses only the production public WebSocket. It must not use private sockets, API keys, authentication headers, or any order endpoint. Sandbox/testnet evidence must be labelled separately and must never be mixed into production market-data evidence.

## 24-hour production public L2 capture

The existing `scripts/capture_l2_continuous_pipeline.py` is a read-only L2 recorder. Its default endpoint is the India sandbox public socket. Always pass the production public endpoint explicitly for this capture.

Run on a persistent, operator-controlled host (not a short-lived Vercel function or temporary sandbox). From the canonical repository root:

```bash
python scripts/capture_l2_continuous_pipeline.py \
  --endpoint wss://public-socket.india.delta.exchange \
  --symbols BTCUSD ETHUSD \
  --duration 86400 \
  --output-dir research/captures/delta_india_production_24h
```

Before starting, check available disk space and confirm the host clock is synchronized. Keep the process attached to a persistent terminal/session manager and preserve stdout/stderr. Do not run multiple captures into the same output directory.

After completion, locate the generated summary JSON and verify it using:

```bash
python scripts/verify_l2_capture_artifacts.py --summary <path-to-summary.json>
```

Archive the raw JSONL, summary JSON, verifier output, exact start/end UTC times, endpoint, symbols, source commit, script SHA-256, raw-artifact SHA-256, reconnect count, stale intervals, sequence gaps, and any interruptions. A clean local sequence counter is not proof of uninterrupted venue-side coverage during disconnections. Classify the result as PARTIAL if continuity or provenance requirements are not met. Do not repair, rewrite, or concatenate raw capture files after the run.

The operator must review the endpoint subscription acknowledgement and first valid snapshot before treating the stream as usable. If the venue rejects the subscription or returns an unexpected schema, stop and preserve the failed attempt as diagnostic evidence; do not silently switch endpoints.

## Delta India BTCUSD futures cost baseline

The official Delta India contract specification currently lists BTCUSD perpetual maker fee 0.02%, taker fee 0.05%, lot size 0.001 BTC, and an eight-hour funding interval. The official fee page states 18% GST applies to trading fees. These are published reference values, not a guarantee of the account's effective tier or future schedule.

For a conservative paper model before account-specific verification:

- Maker fee per fill: 2.00 bps before GST; 2.36 bps including 18% GST.
- Taker fee per fill: 5.00 bps before GST; 5.90 bps including 18% GST.
- Maker/maker round trip: 4.72 bps in fees, before spread, adverse selection, funding, and other costs.
- Taker/taker round trip: 11.80 bps in fees, before spread, market impact, funding, and other costs.
- Do not assume a maker fill merely because a passive limit was submitted. Unfilled orders earn no simulated fill; partial fills must be modelled by quantity and time.
- Funding is variable. Apply the observed signed funding rate for each funding event crossed by the simulated holding interval; do not replace it with a fixed assumed rate.
- Include spread crossing and slippage separately from exchange fees. Until measured, use conservative adverse assumptions and mark them as assumptions, not empirical observations.

Recheck the official fee page and contract specification before any future release because Delta may change rates, promotions, contract metadata, and eligibility. Do not apply Global Delta fee rates to Delta India.

Official references:
- https://www.delta.exchange/fees?tab=trading-fees
- https://www.delta.exchange/en/contracts
- https://www.delta.exchange/support/solutions?articleId=80001132759

## Passive-fill calibration — protocol prepared, not executed

Purpose: estimate whether paper assumptions about passive fills are credible. This is not a live-trading test and this document does not place orders.

Proposed bounded design, pending a separate explicit execution approval:

1. Venue/environment: Delta India sandbox/testnet only. Confirm the active sandbox endpoints from `core/exchanges/delta/delta_environments.py`; never substitute production credentials or production order endpoints.
2. Instrument: BTCUSD only for the first calibration batch. Expand only after reviewing the first batch.
3. Order behavior: post-only/passive limit orders only; no market orders, no aggressive repricing, no leverage increase, no position carry. A cancel/replace, if later authorized, must be separately bounded and counted.
4. Hard bounds to be fixed in a separate execution approval: maximum order count, maximum notional per order, maximum aggregate notional, maximum wall-clock duration, maximum outstanding orders, and a kill/stop condition.
5. Record for every proposed/approved order: local monotonic and UTC timestamps, venue order acknowledgement, instrument, side, limit price, quantity, best bid/ask and depth at submission, queue/depth proxy, subsequent book updates, fills and partial fills, cancel acknowledgement, and raw event hashes. Never log credentials or authorization headers.
6. Measure fill probability by time-at-price and queue/depth proxy; time-to-first-fill; partial-fill ratio; adverse selection after fill at fixed horizons; spread and mid-price movement; cancel latency; and data gaps. Separate no-fill outcomes from missing telemetry.
7. Reject the sample as invalid if acknowledgements, event ordering, book continuity, timestamps, or raw-artifact integrity cannot be established. Do not tune strategy parameters on this calibration sample.
8. After any separately authorized testnet run, independently verify artifacts and report confidence limits and sample limitations. Testnet fills are not proof of production queue position or execution quality.

No test orders have been placed. Actual execution requires a new, explicit user approval after the bounds, account/environment, and operational safeguards are reviewed.

## Current safety and release state

```text
PAPER_MODE=True
LIVE_MODE=False
LIVE_EXECUTE=False
ALLOW_LIVE=False
D1-D10=UNDECIDED
Policy freeze implementation=NOT AUTHORIZED
Production readiness=NOT READY
```

This plan does not alter policy, strategy parameters, execution behavior, or live-trading permissions.
