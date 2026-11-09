# QuantEngine — Operational Runbook (Phase 9P-i)

A repeatable, from-fresh-environment path to run the complete PAPER
product stack, with every failure clearly classified.

Target system:

```text
   Tkinter Desktop Client (core.client, 9P-h)
                 |
                 |  HTTP + Bearer auth
                 v
        Control & Monitoring API (core.monitoring, 9P-f/9P-g)
                 |
                 v
        EngineLifecycle (core.runtime.lifecycle)
                 |
                 v
        RealTimeEngine -> PaperRuntime -> BrokerEngine (dry_run)
                 |
      +----------+--------------------------+
      |          |                          |
  Universe   Multi-symbol            Delta REST/WebSocket
  provider   symbol pipelines        market data (optional)
  universe
```

There is **no live trading path** in this runbook. Everything below is
PAPER-only. Zero new runtime dependencies are required beyond
`requirements.txt`; the desktop client is stdlib-only.

---

## 0. Environment requirements

| Item          | Requirement                                  |
| ------------- | -------------------------------------------- |
| OS            | Windows (this runbook uses PowerShell)       |
| Python        | **3.12.x** (3.12.10 verified)                |
| Display       | Required only for the Tkinter desktop client |
| Network       | Optional (see PAPER local mode)              |
| Delta account | Optional (see PAPER + Delta mode)            |

Check the interpreter:

```powershell
python --version
```

---

## 1. Fresh-environment install

```powershell
# 1) create a virtualenv
python -m venv .venv

# 2) activate it (PowerShell)
.\.venv\Scripts\Activate.ps1

# 3) install requirements
python -m pip install -r requirements.txt

# 4) confirm
python --version
```

Nothing from the desktop client is an extra dependency: it uses only the
standard library (tkinter, tkinter.ttk, urllib, json, threading, queue,
time). No additional commands are needed to run the client.

---

## 2. Configuration (environment variables)

All configuration is read from environment variables (and an optional
`.env` file at the repository root loaded by `config/settings.py`).
Settings are **PAPER by default** (`PAPER_MODE=True`, `LIVE_MODE=False`,
`LIVE_EXECUTE` empty).

### 2.1 PAPER local mode (minimum configuration)

Nothing is required beyond the defaults. This mode uses no network, no
credentials, and an explicit symbol universe.

| Variable  | Default            | Meaning                          |
| --------- | ------------------ | -------------------------------- |
| `SYMBOLS` | `BTCUSDT,ETHUSDT`  | Comma-separated explicit members |
| `TIMEFRAME` | `1m`             | Bar timeframe                    |
| `PAPER_MODE` | `True`          | PAPER runtime (do not set false) |
| `UNIVERSE` | `explicit`        | See 2.3                            |

### 2.2 Delta venue and personal API credentials

Select the exact Delta region and environment before using private
clients or provider-backed data. You can configure your own key locally
without sending it to ChatGPT or committing it:

```powershell
python scripts/configure_delta_credentials.py
```

Choose INDIA or GLOBAL, then SANDBOX or PRODUCTION. The key and secret
prompts are hidden. The script updates only the selected Delta credential
pair in the ignored repository-root `.env`, preserves unrelated settings,
replaces stale Delta credential entries, and restricts file permissions
where the operating system supports POSIX mode bits. It never enables live
trading. Then verify the key:

```powershell
python scripts/check_delta_credentials.py
```

For manual setup, an India account can use:

```dotenv
DELTA_REGION=INDIA
DELTA_ENVIRONMENT=SANDBOX
DELTA_INDIA_SANDBOX_API_KEY=your-personal-key
DELTA_INDIA_SANDBOX_API_SECRET=your-personal-secret
```

For India production use `DELTA_ENVIRONMENT=PRODUCTION` with
`DELTA_INDIA_API_KEY` / `DELTA_INDIA_API_SECRET`. Global accounts use
their matching Global pair. Never copy keys between regions or
environments. Keep actual values only in the local `.env` file or
secret store; never commit them or paste them into source files.

Paper trading does not require private credentials; public market data
is sufficient. Private account reads require the matching personal
key pair. The selected region/environment now pins provider REST hosts,
contract discovery and the LIVE client factory. Missing or unknown
selection fails closed instead of silently using Global.

Verify your own configured key pair before running the engine:

```powershell
python scripts/check_delta_credentials.py
```

This performs one signed account-identity read only. It does not read
balances, place orders, or print your API key, secret, or account ID.
A successful check confirms authentication for the selected region and
environment; it does not enable live trading.

### 2.3 PAPER + Delta market data

Delta connectivity is **optional and best-effort**; the runtime still
starts safely when Delta is unreachable (see Troubleshooting).

| Variable  | Default | Meaning                                  |
| --------- | ------- | ---------------------------------------- |
| `DELTA_API_KEY` | `""` | Delta account API key (optional)      |
| `DELTA_API_SECRET` | `""` | Delta account API secret (optional) |
| `UNIVERSE` | `explicit` | `provider` to drive eligibility from live Delta liquidity/history |
| `MIN_QUOTE_VOLUME_24H` | *(unset)* | Optional >= bound on 24h USD volume when `UNIVERSE=provider` |
| `MIN_HISTORY_BARS` | *(unset)* | Optional >= bound on available history bars |
| `PROVIDER_HISTORY_LOOKBACK_DAYS` | `7` | Lookback (days) used by the history provider |

Data honesty: when `UNIVERSE=provider`, a symbol with missing / zero /
unparseable liquidity or history is **DENIED**, never assumed eligible.
An empty eligible universe is a valid state, not an error.

**Current strategy-feed limitation:** the canonical PAPER runtime still
fails closed at the strategy-candle subscription seam. Legacy ticker marks
are reference-only and are never converted into traded OHLCV. The verified
Global socket transport is tested but not yet wired into the canonical
PAPER engine; India capture classifications remain advisory-only. Therefore
starting PAPER mode does not yet mean exchange candles are reaching strategy
engines. Use verified historical datasets for research/backtests until the
venue-specific live-candle integration is separately certified.

### 2.4 Importing historical CSV data for research

A venue-neutral CSV importer is available for historical OHLCV exports from
NSE/Sensex, forex, crypto, or other data vendors. It validates and normalizes
rows but does not fetch data or certify the vendor's completeness. Use the
Python API:

```python
from core.research.acquisition.csv_ohlcv import load_ohlcv_csv

dataset = load_ohlcv_csv(
    "data/imports/NIFTY_1m.csv",
    symbol="NIFTY",
    source="your-broker-export",
    timeframe="1m",
    source_timezone="Asia/Kolkata",  # required for naive local timestamps
)
print(dataset.row_count, dataset.dataset_hash, len(dataset.gaps))
bars = list(dataset.bars)
```

For ISO-8601 timestamps with an explicit UTC offset, `source_timezone`
can be omitted. Numeric timestamps require an explicit `timestamp_unit`
(`seconds`, `milliseconds`, `microseconds`, or `nanoseconds`). Duplicate
timestamps, symbol mismatches, invalid OHLCV, and ambiguous local times are
rejected. Time-spacing gaps are reported in `dataset.gaps`; no bars are interpolated
or fabricated. These are wall-clock spacing observations, not proof of missing
trading bars: overnight closures, exchange holidays, and session breaks can
also appear because no venue calendar is applied. The hash covers normalized
rows in chronological order. Treat this as validated input, not proof of
complete source history.

For the project's scoped-backtest gate, supply `venue`, `region`,
`environment`, `instrument`, and an explicit `source_timestamp`. The
result includes a `scope_provenance` record. Its default completeness is
`UNKNOWN`, which the backtest gate rejects. Only set
`completeness="COMPLETE"` and `pagination_exhausted=True` when you have
independently confirmed the source export covers the intended period; this
is an operator attestation, not something CSV parsing can prove.

### 2.5 European options analytics (research only)

The research options module provides Black-Scholes European call/put values,
delta, gamma, vega, theta, rho, and a bounded implied-volatility solver.
Values are per underlying unit; the module does not apply exchange lot sizes,
contract multipliers, transaction costs, margin, early exercise, or discrete
dividend schedules. Use verified option contract metadata and market quotes;
this model is not an execution or profitability signal.

```python
from core.options import calculate_option_valuation, implied_volatility

value = calculate_option_valuation(
    spot=22500, strike=22600, time_to_expiry_years=0.18,
    volatility=0.34, option_right="call",
    risk_free_rate=0.065,
)
iv = implied_volatility(
    market_price=value.fair_value, spot=22500, strike=22600,
    time_to_expiry_years=0.18, option_right="call",
    risk_free_rate=0.065,
)
```

Theta is returned per year and per ACT/365 day. Vega and rho are derivatives
per 1.0 absolute change in volatility and rate. Expiry valuation returns
intrinsic value and boundary delta, with other Greeks zero.

Scale a per-unit valuation into a signed position using the verified option
lot size and contract multiplier:

```python
from core.options import scale_option_position

exposure = scale_option_position(
    value, spot=22500, signed_contracts=2, lot_size=25,
    contract_multiplier=1,
)
print(exposure.delta_notional, exposure.vega_per_volatility_point)
```

Negative contract counts represent short positions. The result reports model
premium value and signed Greeks; it is not a margin, liquidation, or maximum-loss
calculation.

The canonical instrument registry retains option `lot_size` and
`contract_multiplier`. Option contract metadata is considered complete only
when the underlying, call/put right, strike, expiry timestamp, lot size, and
multiplier are all valid. This does not make options eligible for the existing
spot/perpetual strategy engine. A deterministic single-position scenario
repricer is also available through `evaluate_option_scenario`; it reprices
under spot, volatility, and elapsed-time shocks and scales model P&L by signed
contracts, lot size, and multiplier. It is not a portfolio margin or
liquidation simulation.

### 2.6 Control API

The Control & Monitoring API binds to **127.0.0.1 only** and is **OFF
by default**. It fails **closed**: if enabled without a token, it refuses
to start at all.

| Variable  | Default      | Meaning                              |
| --------- | ------------ | ------------------------------------ |
| `CONTROL_API_ENABLED` | `False` | Set `True` to start the API   |
| `CONTROL_API_TOKEN` | `""` | **Required** bearer token when enabled |
| `CONTROL_API_HOST` | `127.0.0.1` | localhost only (do not change to 0.0.0.0) |
| `CONTROL_API_PORT` | `8787` | TCP port                        |
| `CONTROL_API_POLL_SECONDS` | `10` | Lifecycle poll cadence    |

The API is read-only except the four allowlisted PAPER lifecycle verbs.

### 2.7 Desktop client

The client reads its own env variables (not the server's).

| Variable  | Default  | Meaning                                 |
| --------- | -------- | --------------------------------------- |
| `QENGINE_CLIENT_TOKEN` | `""` | Client token (falls back to `CONTROL_API_TOKEN`) |
| `QENGINE_CLIENT_HOST` | `127.0.0.1` | API host           |
| `QENGINE_CLIENT_PORT` | `8787` | API port              |
| `QENGINE_CLIENT_POLL` | `3.0` | Read polling interval (seconds) |
| `QENGINE_CLIENT_TIMEOUT` | `5.0` | HTTP request timeout (seconds) |

---

## 3. Start the engine + Control API

In one terminal (PowerShell), python must be the activated venv, and the
API enabled **with a token**:

```powershell
# PAPER local mode with the Control API
$env:CONTROL_API_ENABLED = "True"
$env:CONTROL_API_TOKEN  = "change-me-strong-secret"

python main.py
```

Expected output includes:

```text
Mode      : PAPER TRADING (multi-symbol runtime)
Control API: ENABLED (localhost, token-protected, PAPER-only)
```

The process blocks, polling for live candles. The API serves reads and
the PAPER control verbs on `127.0.0.1:8787`.

To run Delta-backed eligibility instead:

```powershell
$env:UNIVERSE = "provider"
$env:CONTROL_API_ENABLED = "True"
$env:CONTROL_API_TOKEN  = "change-me-strong-secret"
# optional thresholds
$env:MIN_QUOTE_VOLUME_24H = "100000"
$env:MIN_HISTORY_BARS     = "60"
python main.py
```

> PAPER local mode with the API **disabled** (the default) also works
> and matches the historical `run_paper_forever` behavior, just with no
> HTTP surface.

---

## 4. Start the desktop client

In a **second terminal** (with a display), set the client token to the
same secret and launch:

```powershell
# must match the API token from step 3
$env:QENGINE_CLIENT_TOKEN = "change-me-strong-secret"

python -m core.client
```

Both entrypoints are equivalent:

```powershell
python -m core.client        # same as:
python -m core.client.app
```

The window opens with a **Dashboard** and connection indicator. When the
client first connects to the API, the header turns green and shows
`connected` and the engine lifecycle (`engine: RUNNING`).

**Never** set `QENGINE_CLIENT_HOST` to anything but the API's own
localhost address.

---

## 5. Verify the system is healthy

### 5.1 In the desktop client

Confirm, on the various tabs:

- **Dashboard**: `connected`, `engine: RUNNING`, `Eligible symbols` count
- **Universe**: the eligible symbol symbols
- **Trading → Positions / Orders / Risk**: live PAPER state
- **Performance**: the server's authoritative report (never recomputed
  in the client)

### 5.2 From the shell (server is authoritative)

```powershell
$h = @{ Authorization = "Bearer change-me-strong-secret" }
Invoke-RestMethod -Uri "http://127.0.0.1:8787/health" -Headers $h
Invoke-RestMethod -Uri "http://127.0.0.1:8787/universe" -Headers $h
Invoke-RestMethod -Uri "http://127.0.0.1:8787/performance" -Headers $h
```

Every `GET` returns `200` JSON. Read endpoints:

```text
/health /universe /subscriptions /runtimes /market /signals
/positions /orders /account /risk /performance /errors
```

---

## 6. Lifecycle control

The only write is `POST /control` with an allowlisted command:

```powershell
$body = @{ command = "stop" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8787/control" `
  -Headers $h -Body $body -ContentType "application/json"
```

| Command          | Meaning                                                        |
| ---------------- | -------------------------------------------------------------- |
| `start`          | Start the engine + poll loop (idempotent)                      |
| `stop`           | Graceful stop (finish the iteration, join, `engine.stop()`)    |
| `restart`        | `stop` then `start`                                            |
| `emergency_stop` | Immediate local PAPER shutdown, highest priority, idempotent   |

All four are available from the desktop client's control bar, each with
a confirmation dialog (Emergency Stop has the strongest).
**Emergency stop is a PAPER-runtime safety feature**; there is no live
emergency-stop path.

---

## 7. Shutdown (safe)

- In the client, **Stop** (or `Emergency Stop`) → the runtime halts, the
  lifecycle reaches `STOPPED`, and `python main.py` exits.
- **Closing the desktop client window does NOT stop the engine.** The
  client only stops its own poller; the engine keeps running.

---

## 8. Emergency stop

`emergency_stop` immediately cancels the poll loop and calls
`engine.stop()` without waiting for the loop's current iteration. It
returns `STOPPED`, is idempotent (safe to call twice), and remains
STOPPED (the engine can be restarted afterward). It is a local,
PAPER-only command.

---

## 9. Reconnection behavior

- **Engine subscriptions** reconnect independently with exponential
  backoff (`data/realtime/reconnect_policy.py`); one stream failure
  never kills the engine loop. A `max_attempts` budget, when configured,
  marks the subscription FAILED instead of looping forever.
- **Universe refresh**: one failed discovery pass is recorded in
  `RefreshScheduler.errors` and never kills the loop.
- **Provider universe**: unavailable data becomes a DENY, never a fake
  "eligible".
- **Desktop client**: on a disconnect the header goes `disconnected`;
  the client auto-reconnects and resumes polling without an engine
  restart.

---

## 10. Troubleshooting

| Symptom | Likely cause | Resolution |
| ------- | ------------ | ---------- |
| `Control API: disabled (default)` | `CONTROL_API_ENABLED` not `True` | Set it `True` and restart |
| API won't start / `fail closed` | API enabled with an empty token | Set `CONTROL_API_TOKEN` |
| Client cannot connect | No API running, wrong host/port, or client token mismatch | Confirm `python main.py` is up; match `QENGINE_CLIENT_TOKEN` to `CONTROL_API_TOKEN` |
| Client shows `401` / `authentication failed` | Client token differs from API token | Use the same secret on both sides |
| `connection refused` | API not running or wrong port | Check `python main.py` output and `QENGINE_CLIENT_PORT` |
| Empty universe (`eligible_count: 0`) | `UNIVERSE=provider` but Delta unreachable or all symbols below threshold | This is a valid state, not an error; engine stays healthy; later refresh can populate symbols when data is available |
| Delta connectivity unavailable | No network / no credentials | Runtime still starts; universe becomes empty/denied, never fabricated |
| No market data flowing | Delta WebSocket unreachable | Subscriptions reconnect per policy; check `/errors` and `/subscriptions` |
| `Universe mode` shown as `explicit` when expecting provider | `UNIVERSE` is `explicit`, or provider path not selected | Set `UNIVERSE=provider` |

---

## 11. Security notes

- Secrets are **environment/config only** — never in source, logs,
  URLs, or serialized reports.
- The API binds to **127.0.0.1 only**, is **off by default**, and is
  **bearer-authenticated** with constant-time token comparison.
- Unsupported HTTP methods, unknown routes, unsupported control verbs,
  and malformed bodies all fail safely (`401/404/400/500`).
- The desktop client is a **thin HTTP client**: it imports no engine
  internals and never computes strategy/risk/position/order values.
- Closing the client never stops the engine.

## 12. Multi-machine / remote access

**Not supported and intentionally not enabled.** The API is hard-bound
to `127.0.0.1`; do not change it to `0.0.0.0`. A future phase addresses
secure remote/mobile access. For now, run the client on the same host as
the engine.

---

## 13. Full verification checklist

```text
[ ] python --version  -> 3.12.x
[ ] python -m pip install -r requirements.txt
[ ] python -m compileall .   (clean)
[ ] python -m pytest tests/  (all pass)
[ ] python main.py  (PAPER, Control API ENABLED)
[ ] python -m core.client  (client connects, polls, controls)
[ ] GET /health /universe /performance  -> 200
[ ] POST /control stop / start / restart / emergency_stop
[ ] client window close  -> engine keeps running
[ ] grep secrets: no token/key in source, logs, or reports
```
