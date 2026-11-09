# QuantEngine operator market-support matrix

This matrix distinguishes implemented interfaces from declared architecture and research plans. A market-family enum or a passing unit test is not a production adapter.

| Market / venue | Current implemented scope | Operational boundary |
|---|---|---|
| Delta Exchange Global | Region/environment-pinned REST client, personal key setup, read-only identity and public product-catalog check, option-chain and contract tooling | Production strategy candle delivery remains fail-closed until a verified Global evidence bundle is supplied. No live trading certification. |
| Delta Exchange India | Region/environment-pinned REST client and credential selection; India public candle observations and advisory fixture analysis | India fixture harness is test-only/advisory. It does not authorize or wire a production strategy feed. |
| NSE / BSE via Flattrade | Local personal credential/token provisioning and a read-only REST client are implemented; the client is not yet wired into the runtime | Authentication and individual read-only calls are available; production streaming, canonical candle/option-chain normalization, paper runtime wiring and live orders are not yet connected. |
| Forex via Flattrade | No concrete FX broker adapter in this repository yet | Not available through QuantEngine. |
| Crypto beyond Delta | Capability architecture may support additional venues | No additional venue should be treated as connected without a concrete adapter and conformance/evidence tests. |

## Current one-command check

`python scripts/quantengine_doctor.py` verifies the selected Delta credential configuration, authenticated identity and public product catalog. It is a read-only connectivity check. A PASS does not certify strategy candles, streaming freshness, historical-data quality, paper strategy execution, order permissions or profitability.

## Flattrade integration target

The intended Flattrade target is the vendor's Pi API and its official Python client repository:

- API documentation: https://pi.flattrade.in/docs
- Vendor Python client: https://github.com/flattrade/pythonAPI

The vendor documentation describes instrument search/metadata, quotes, intraday and daily price series, option-chain retrieval, WebSocket market feeds, and account/order APIs. The Python client setup uses an app API key/secret plus a user ID and generated session token. Its setup guide states that session tokens expire daily at 5:00 AM IST.

The vendor token exchange also requires the request to originate from the API key's registered private static IP. A safe QuantEngine adapter must therefore implement and test, before use:
1. Local-only secret provisioning for app key, app secret, user ID and short-lived session token; no secrets in source control, logs or chat.
2. A token refresh/re-authentication workflow that does not expose credentials or silently reuse an expired token.
3. Read-only identity/session validation, instrument search, quote, historical candle and option-chain retrieval.
4. WebSocket lifecycle, reconnect/resubscribe, exchange-token mapping, timestamp/sequence/finality checks and stale-data gates.
5. NSE/BSE/NFO/CDS instrument metadata, lot size, tick size, expiry, strike, option side and market-session rules.
6. Paper-only integration and adapter conformance tests before any order API work.
7. Separate order-write authorization, journaling, reconciliation and explicit safety review; credential setup alone must never arm live trading.

Do not enter Flattrade credentials into the Delta setup utility. Flattrade token provisioning is implemented; the Flattrade market-data adapter and any execution integration remain future work.
