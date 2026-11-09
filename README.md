# QuantEngine

QuantEngine is a multi-market research and trading-engine project. Delta has a personal credential and read-only connectivity path. Flattrade personal token provisioning is now available, but its market-data and execution adapter is not yet implemented.

## Use your own Delta API keys

1. From the repository root, run:
   `python scripts/configure_delta_credentials.py`
2. Select the exact region (`INDIA` or `GLOBAL`) and environment (`SANDBOX` or `PRODUCTION`).
3. Confirm the update, then enter your API key and secret at the hidden prompts.
4. Run the offline configuration check: `python scripts/quantengine_preflight.py`
5. Verify the selected key with:
   `python scripts/check_delta_credentials.py`

The setup writes to the ignored local `.env`; it does not print secrets or enable live execution. See [Personal Delta API key setup](docs/OPERATOR_PERSONAL_DELTA_API_KEYS.md) and the [market support matrix](docs/OPERATOR_MARKET_SUPPORT_MATRIX.md).

## Flattrade token setup (authentication only)

A local-only Flattrade token provisioning utility is available:
`python scripts/configure_flattrade_credentials.py`

Register the exact loopback redirect URL shown by the utility in your Flattrade app and ensure the token exchange runs from the API key's registered private static IP. This provisions your personal Flattrade credentials and short-lived session token in the ignored local `.env`. **It does not yet connect Flattrade market data or enable NSE/BSE/Forex trading.** See [Flattrade setup details](docs/phase480-flattrade-local-token-setup.md).

After provisioning your token, you can verify the read-only Flattrade session with:
`python scripts/check_flattrade_connection.py`

The check only calls the user-details endpoint; it does not access balances, positions or orders.

## Safety status

Paper/research workflows are separate from live execution. Live order writing remains disarmed by default. Passing a focused CI gate does not certify profitability or full production readiness.
