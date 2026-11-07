# Owner governance HTTP API

## Capability

The owner-governance state machine now has a dedicated loopback HTTP transport
that authenticates every mutation through a verified OIDC bearer token. It
binds that token only for the request and delegates identity, tenant membership,
expiry, and active-session checks to the existing trusted principal and
authenticated governance adapters.

Routes:

- `POST /v1/tenants/{tenant}/members` — owner invites a member (PENDING).
- `POST /v1/tenants/{tenant}/members/{subject}/decision` — owner approves or rejects.
- `POST /v1/tenants/{tenant}/credentials` — approved member submits credential metadata.
- `POST /v1/tenants/{tenant}/credentials/{credential}/decision` — owner approves/rejects.
- `DELETE /v1/tenants/{tenant}/credentials/{credential}` — owner revokes an approved credential.

The API accepts credential identifiers, account identifiers, and a SHA-256
fingerprint only. It rejects additional fields, including caller-supplied actor
IDs, roles, API keys, or API secrets. It never returns credential material.
Responses are non-cacheable; request logging is disabled; internal verifier and
persistence exceptions are not echoed. A missing or malformed bearer header is
401; a token that fails verification or fails the authenticated tenant/owner
policy is deliberately collapsed to 403 by the facade, avoiding identity-state
oracle details. The server refuses non-loopback binds.

## Deployment and limitations

Compose this transport with `OidcTenantPrincipalSource`, a production token
verifier, an authoritative membership resolver, and a session-status validator.
The transport itself does not implement OIDC cryptography, identity provisioning,
TLS termination, rate limiting, or production database isolation. Keep it on
loopback behind a separately authenticated/TLS-terminating trusted gateway if
remote operator access is required. The SQLite governance repository remains
test/development only; the current PostgreSQL tenant-isolation adapter is not
production-admissible. This API therefore does not certify production readiness.

## Verification

The integration tests exercise verified owner and member identities, invite
and approval transitions, credential metadata submission/approval/revocation,
missing and invalid bearer tokens, tenant mismatch, actor spoofing, raw secret
field rejection, and loopback-only binding. These are transport tests using
injected test verifiers and SQLite, not evidence of a deployed identity provider,
database isolation, or live trading authorization.
