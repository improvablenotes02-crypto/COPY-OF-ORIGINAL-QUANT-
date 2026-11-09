# Operator: configure your personal Delta Exchange API keys

This procedure configures credentials belonging to the operator. It does not create QuantEngine member accounts, grant access to other people, or enable live order execution.

## Before you begin

- Use API credentials created in your own Delta Exchange account.
- Select the matching venue (India or Global) and environment (Sandbox or Production).
- Start with Sandbox. Do not use production credentials until you have independently reviewed the exchange permissions and operational risks.
- Never paste API keys or secrets into chat, GitHub issues, pull requests, source files, screenshots, or support logs.
- Keep the API key permissions as narrow as the exchange permits. The verifier uses an authenticated account-identity read only; it does not need order-write permission.

## Configure credentials locally

From the repository root, run:

```bash
python scripts/configure_delta_credentials.py
```

The script requires an interactive terminal. It asks for:

1. Region: `INDIA` or `GLOBAL`.
2. Environment: `SANDBOX` or `PRODUCTION`.
3. Confirmation before replacing existing managed Delta credential entries.
4. API key and API secret through hidden prompts.

The script writes the selected pair to the repository-root `.env` file, preserves unrelated settings, removes obsolete managed Delta key names, writes through a temporary file, and atomically replaces `.env`. On POSIX systems it attempts mode `0600`. It refuses to replace a symbolic-link `.env`.

Credential variable mapping:

| Selection | Key variable | Secret variable |
|---|---|---|
| Global / Production | `DELTA_API_KEY` | `DELTA_API_SECRET` |
| Global / Sandbox | `DELTA_SANDBOX_API_KEY` | `DELTA_SANDBOX_API_SECRET` |
| India / Production | `DELTA_INDIA_API_KEY` | `DELTA_INDIA_API_SECRET` |
| India / Sandbox | `DELTA_INDIA_SANDBOX_API_KEY` | `DELTA_INDIA_SANDBOX_API_SECRET` |

The selected venue and environment are also stored as `DELTA_REGION` and `DELTA_ENVIRONMENT`.

## Verify the selected credentials

Run:

```bash
python scripts/check_delta_credentials.py
```

This command makes one authenticated account-identity request. A successful result confirms that the configured key pair authenticated against the selected Delta venue/environment. It does not verify balances, trading permissions, market-data completeness, or order execution.

On failure, the script emits a fixed error category and a safe hint. Provider exception/response details are deliberately redacted because they may contain sensitive request data.

The verifier does not place, amend, or cancel orders. It closes its HTTP session when finished.

## Secret handling

- The root `.gitignore` excludes `.env` and `.env.*` while allowing the non-secret `.env.example`.
- Do not remove these ignore rules or force-add `.env`.
- Before any commit, check `git status --short` and inspect staged filenames. If a credential file is staged, unstage it and rotate any secret that may have been exposed.
- If a key is exposed, revoke it in the Delta account and create a replacement. Do not merely delete the exposed file or Git commit.
- Do not send API keys or secrets to QuantEngine maintainers through chat.

## Execution safety boundary

Credential setup and identity verification do not authorize live trading. Live order execution remains disarmed by default. Passing this check is not a production-readiness certification, strategy validation, or evidence of profitability. Use Sandbox and paper/research workflows first, and require the separate execution-safety and release gates before considering any live deployment.
