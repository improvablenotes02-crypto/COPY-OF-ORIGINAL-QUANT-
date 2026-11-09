# Phase 481 - Flattrade read-only REST client

QuantEngine now has an HTTPX-backed, injectable read-only Flattrade Pi REST client. It exposes only the documented endpoints:
- `UserDetails` for the authenticated user's enabled exchange list and account metadata
- `SearchScrip` for instrument/token discovery
- `GetQuotes` for current quote snapshots
- `TPSeries` for intraday candle history
- `GetOptionChain` for option-chain contract discovery

Requests use the documented form fields `jData` (compact JSON) and `jKey` (session token) against the fixed official `PiConnectAPI` origin. The client intentionally has no order, modify, cancel, exit, holdings, positions or balance methods.

All response failures are reduced to safe error categories; provider messages and session tokens are not included in raised exception text. Run `python scripts/check_flattrade_connection.py` after provisioning the session token to validate `UserDetails` and list the number of enabled exchange segments. It does not reveal account identifiers.\n\nThe client is not yet wired into the production runtime, strategy candle path, option-chain normalizer or paper execution manager. The next integration work must map vendor response fields into canonical instruments/quotes/candles and apply exchange-session, timestamp, finality, freshness and continuity gates before any strategy use.
