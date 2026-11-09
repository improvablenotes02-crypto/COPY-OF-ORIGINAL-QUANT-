# Phase 480 - Local Flattrade token provisioning

Run from the repository root:

```powershell
py scripts\configure_flattrade_credentials.py
```

Before running, create a Flattrade Pi API application, register the exact local redirect URI printed by the command (default `http://127.0.0.1:8080/`), and confirm that the API key's registered private static IP matches the machine making the token-exchange request. Flattrade documents that the token is returned only when the request originates from the registered private static IP. The command prompts for the app API key and secret with hidden input, opens the Flattrade login URL, receives the one-time callback code on a loopback-only HTTP listener, exchanges it once, and atomically writes the app key, app secret, returned client ID and session token to the ignored local `.env`.

Security boundaries:
- The callback server binds only to `127.0.0.1`; callback URLs and one-time codes are never logged. The token-exchange request must originate from the API key's registered private static IP.
- API secrets, request codes, signing hashes and returned tokens are never printed.
- Failed token exchange does not mutate the existing `.env`.
- No balances, positions, quotes, orders or order endpoints are called.
- Token renewal is an operator action. Flattrade's published setup guide states that session tokens expire daily at 5:00 AM IST.
- The credential setup does not create a Flattrade market-data adapter and does not enable live execution.

The official vendor token endpoint requires `api_key`, `request_code`, and SHA-256(`api_key + request_code + api_secret`) in the `api_secret` field. Success returns a `client` and `token` with `status: Ok`. See the official [Pi API documentation](https://pi.flattrade.in/docs) and vendor [Python API setup guide](https://github.com/flattrade/pythonAPI/blob/main/token_generator/setup.md).
