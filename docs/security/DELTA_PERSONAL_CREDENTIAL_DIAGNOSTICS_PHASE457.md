# Phase 457 — redacted personal Delta credential diagnostics

## Scope

The personal credential check uses the configured Delta region/environment client
and calls only the signed identity endpoint GET /v2/users/trading_preferences.
It does not read balances, positions, orders, or fills and does not invoke an
exchange write endpoint. The signed REST transport may retry transient
connection/read-timeout failures on that same read-only endpoint.

A successful result means only that the configured key pair authenticated the
identity request against the selected venue at that time. It does not establish
trading permission, withdrawal permission, account ownership, account health,
available funds, or live-execution authorization.

## Failure diagnostics

The CLI may inspect the HTTP status and a provider error code, but it reduces
them through the existing classify_auth_error taxonomy to a fixed set:

- INVALID_API_KEY
- INVALID_SIGNATURE
- TIMESTAMP_ERROR
- IP_NOT_WHITELISTED
- PERMISSION_DENIED
- AUTHENTICATION_FAILED

Unknown codes, malformed response bodies, transport errors, and unrecognized
provider responses fall back to AUTHENTICATION_FAILED. Only the fixed
category and a static operator hint are emitted. Raw provider messages, error
codes, response bodies, context objects, exception text, API keys, API secrets,
and account identifiers are never printed.

The categories are diagnostic hints, not a complete or authoritative statement
of provider policy. Operators must verify key permissions and IP allowlists in
the Delta account's own security controls. The check does not change credentials,
retry writes, or grant execution authority.

## Verification boundary

The tests use synthetic credentials and fake HTTP responses. They do not contact
Delta and do not establish that any real account is accessible. No real credential
is stored in the repository or CI. Live order writing remains disarmed and
production readiness remains NOT CERTIFIED / HOLD.
