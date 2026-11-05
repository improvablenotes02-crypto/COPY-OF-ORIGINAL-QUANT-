# Delta Environments — Region and Environment Authority

Status: the repository now distinguishes the **Global** and **India**
Delta venues independently from **production** and **demo/testnet**.
This prevents a valid key for one venue from being silently sent to
another venue.

## Official endpoint matrix

The following endpoint origins are documented by Delta's India API
reference. Global endpoints remain supported for legacy Global accounts.

| Region | Environment | REST | Public WebSocket | Private WebSocket |
|---|---|---|---|---|
| GLOBAL | PRODUCTION | `https://api.delta.exchange` | `wss://public-socket.delta.exchange` | `wss://socket.delta.exchange` |
| GLOBAL | SANDBOX | `https://testnet-api.delta.exchange` | UNVERIFIED | UNVERIFIED |
| INDIA | PRODUCTION | `https://api.india.delta.exchange` | `wss://public-socket.india.delta.exchange` | `wss://socket.india.delta.exchange` |
| INDIA | SANDBOX | `https://cdn-ind.testnet.deltaex.org` | `wss://socket-ind-pub.testnet.deltaex.org` | `wss://socket-ind.testnet.deltaex.org` |

India endpoint and WebSocket hosts are taken from Delta's official API
documentation. The Global sandbox WebSocket remains deliberately
unconfigured until separately verified. See
[Delta API documentation](https://docs.delta.exchange/).

## Configuration

Set both dimensions explicitly for a new deployment:

```dotenv
DELTA_REGION=INDIA
DELTA_ENVIRONMENT=SANDBOX
DELTA_INDIA_SANDBOX_API_KEY=...
DELTA_INDIA_SANDBOX_API_SECRET=...
```

For an India production account, use `DELTA_REGION=INDIA`,
`DELTA_ENVIRONMENT=PRODUCTION`, `DELTA_INDIA_API_KEY`, and
`DELTA_INDIA_API_SECRET`.

Global credentials remain separate:
- Global production: `DELTA_API_KEY` / `DELTA_API_SECRET`
- Global demo: `DELTA_SANDBOX_API_KEY` / `DELTA_SANDBOX_API_SECRET`

India credentials are separate:
- India production: `DELTA_INDIA_API_KEY` / `DELTA_INDIA_API_SECRET`
- India demo: `DELTA_INDIA_SANDBOX_API_KEY` / `DELTA_INDIA_SANDBOX_API_SECRET`

Never copy credentials between regions or environments. Do not put
secrets in source control, logs, issue comments, or ChatGPT messages.
Configure them only in the local secret store/environment used by the
deployment.

## Code authority

`core/exchanges/delta/delta_environments.py` is the runtime authority.
Use `configured_client()` to construct from `DELTA_ENVIRONMENT` and
`DELTA_REGION`, or `client_for(environment, region)` to make both
dimensions explicit. Legacy no-region endpoint helpers and default
constructors retain their Global behavior for compatibility; the
new factory reads `DELTA_REGION` (default `GLOBAL`) and does not
cross-fallback credentials.

The authority validates the exact REST origin and refuses unknown
regions, unknown environments, endpoint/region mismatches, missing
credentials, and unverified WebSocket hosts. A region mismatch is not
repaired by trying another endpoint.

## Evidence boundaries

- A public catalog response does not authenticate a private account.
- Demo/testnet balances, orders, positions and fills are not production
  account evidence.
- India and Global product universes and settlement conventions must
  not be mixed in backtests or execution.
- No live-order authority is granted by endpoint selection or account
  identity. Live writes remain independently disarmed.
- The historical 2026-09-25 Global sandbox authentication rejection
  remains an old observation; it does not establish the state of any
  current India demo or production credentials.

## Phase 283 acceptance

Offline regression tests pin all four REST origins, the India public
and private WebSocket origins, rejection of cross-region host pairings,
unknown-region refusal, and four-way credential isolation. These tests
do not contact Delta and do not establish live-account authentication.
