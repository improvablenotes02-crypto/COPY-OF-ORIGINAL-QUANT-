# Operator guide - personal Delta API keys

This is the supported personal API-key path in the current QuantEngine repository. It applies to **Delta Exchange**. It does not configure Flattrade or other broker/exchange adapters.

## Before you start

- Create your own API key and secret in the correct Delta account/region.
- Prefer the least-privileged permissions needed for the task. The verification command requires only the authenticated identity operation.
- Keep the key pair private. Never paste keys into ChatGPT, issues, pull requests, source files, screenshots, or terminal transcripts.
- Use SANDBOX first where available. Production credentials do not arm live trading.

## Configure locally

From the repository root:

```powershell
py scripts\configure_delta_credentials.py
```

Or on macOS/Linux:

```bash
python scripts/configure_delta_credentials.py
```

The script prompts for:
- Region: `INDIA` or `GLOBAL`
- Environment: `SANDBOX` or `PRODUCTION`
- Confirmation before replacing the managed Delta entries
- API key and API secret through hidden input prompts

It updates only the managed Delta credential names in the root `.env` file and preserves unrelated settings. It writes atomically and attempts restrictive file permissions on POSIX systems.

The selected credential pair is region- and environment-specific. The script does not substitute Global credentials for India, or production credentials for sandbox credentials.

## Offline preflight\n\nRun `python scripts/quantengine_preflight.py` first. This checks the exact region/environment, endpoint, credential-pair presence, and disarmed live flags without network access or printing secrets. A pass is local configuration evidence only.\n\n## Verify the key

Run:

```powershell
py scripts\check_delta_credentials.py
```

Or:

```bash
python scripts/check_delta_credentials.py
```

The verifier calls one authenticated account-identity endpoint. It does not read balances, positions, or orders, and it redacts provider exception details and secret values. A successful identity check confirms authentication only; it does not confirm trading permissions, market-data availability, or order execution readiness.

If verification fails:
- Check that the selected region and environment match the key pair.
- Check whether the provider requires outbound-IP allowlisting.
- Check the key's permission for the identity endpoint.
- Check the matching secret and local system clock.
- Re-enter credentials locally rather than sending them in a message.

## Flattrade token provisioning

Run `python scripts/configure_flattrade_credentials.py` to complete the local Flattrade login/token exchange and store your own credentials in the ignored `.env`. Register the exact loopback redirect URL printed by the script in your Flattrade API application. The session token expires daily at 5:00 AM IST and must be renewed by rerunning the setup. This is authentication provisioning only; QuantEngine's Flattrade market-data adapter is not yet implemented. See [Flattrade local token setup](phase480-flattrade-local-token-setup.md).

## Current support boundary

The current personal credential utility configures Delta Exchange only. NSE/BSE/Forex access through Flattrade is not yet implemented in this repository. See [Operator market-support matrix](OPERATOR_MARKET_SUPPORT_MATRIX.md). Do not put Flattrade keys into the Delta utility.

## One-command operator check\n\nFor the normal workflow, run `python scripts/quantengine_doctor.py`. It first performs the offline configuration preflight and stops without network access if the selected key pair is unavailable or any live execution flag is present. If preflight passes, it performs the read-only authenticated identity and public catalog check. It does not access balances, positions or orders and never sends exchange writes.\n\n## Read-only connectivity check\n\nRun `python scripts/check_delta_connection.py` after the identity check. It verifies the authenticated identity and public product catalog using the selected region/environment client. It does not read balances, positions or orders, and does not send exchange writes. The result is connectivity evidence only, not a trading-readiness certification.\n\n## Secret storage and Git

The root `.env` file is ignored by Git. Keep it on the trusted machine where QuantEngine runs. Do not remove the ignore rule or commit it. If a key is accidentally exposed or committed, revoke it at the exchange and create a replacement.

You can confirm Git is not tracking the local file with:

```bash
git check-ignore .env
git status --short
```

If `.env` is already tracked in your checkout, stop and remove it from version control before entering credentials; rotate any previously exposed keys.

## Live-trading boundary

Configuring or verifying a production API key does **not** enable live execution. `ALLOW_LIVE` and `LIVE_EXECUTE` remain disabled by default, and live order writing remains disarmed. Do not change live-safety flags as part of credential setup.

## Current integration scope

This flow configures Delta Exchange credentials only. Other exchange or broker APIs need their own adapter, authentication tests, permission checks, region/environment mapping, and explicit safety review before their keys can be used.
