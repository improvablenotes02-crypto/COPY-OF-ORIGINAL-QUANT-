# QuantEngine

QuantEngine is a multi-market research and trading-engine project. Its current personal exchange-credential setup supports **Delta Exchange** only; other broker/exchange credentials must not be assumed to work until their adapters and tests are implemented.

## Use your own Delta API keys

1. From the repository root, run:
   `python scripts/configure_delta_credentials.py`
2. Select the exact region (`INDIA` or `GLOBAL`) and environment (`SANDBOX` or `PRODUCTION`).
3. Confirm the update, then enter your API key and secret at the hidden prompts.
4. Run the offline configuration check: `python scripts/quantengine_preflight.py`
5. Verify the selected key with:
   `python scripts/check_delta_credentials.py`

The setup writes to the ignored local `.env`; it does not print secrets or enable live execution. See [Personal Delta API key setup](docs/OPERATOR_PERSONAL_DELTA_API_KEYS.md) and the [market support matrix](docs/OPERATOR_MARKET_SUPPORT_MATRIX.md).

## Safety status

Paper/research workflows are separate from live execution. Live order writing remains disarmed by default. Passing a focused CI gate does not certify profitability or full production readiness.
