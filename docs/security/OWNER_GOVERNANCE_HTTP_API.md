# Owner governance HTTP API

## Capability

The owner-governance state machine now has a dedicated loopback HTTP transport
that authenticates every mutation through a verified OIDC bearer token. It
binds that token only for the request and delegates identity, tenant membership,
expiry, and active-session checks to the existing trusted principal and
authenticated governance adapters.

Routes:

- `GET /v1/tenants/{tenant}/members` — owner-only member list with status and permissions.
- `GET /v1/tenants/{tenant}/credentials` — owner-only credential approval queue; metadata and fingerprint only.

- `POST /v1/tenants/{tenant}/members` — owner invites a member (PENDING).
- `POST /v1/tenants/{tenant}/members/{subject}/decision` — owner approves or rejects.
- `DELETE /v1/tenants/{tenant}/members/{subject}` — owner revokes an approved member, clears permissions, and atomically revokes that member's pending and approved credential registrations; the configured owner cannot revoke their own identity.
- `POST /v1/tenants/{tenant}/credentials` — approved member submits credential metadata.
- `POST /v1/tenants/{tenant}/credentials/{credential}/decision` — owner approves/rejects.
- `DELETE /v1/tenants/{tenant}/credentials/{credential}` — owner revokes an approved credential.\n- `DELETE /v1/tenants/{tenant}/members/{subject}` — owner revokes a member and all that member’s pending/approved credentials.

The governance API accepts credential identifiers, account identifiers, and a SHA-256
fingerprint only. Actual broker key/secret material belongs in the encrypted Delta account
registry, protected at rest by an injected encryption provider; this approval API never
receives or returns raw key material. It rejects additional fields, including caller-supplied actor
IDs, roles, API keys, or API secrets. It never returns credential material.
Responses are non-cacheable; request logging is disabled; internal verifier and
persistence exceptions are not echoed. A missing or malformed bearer header is
401; a token that fails verification or fails the authenticated tenant/owner
policy is deliberately collapsed to 403 by the facade, avoiding identity-state
oracle details. The server refuses non-loopback binds and verifies the numeric address returned
by the completed bind, including when the configured host is `localhost`.
Active request handlers are bounded by `max_workers` (default 16, allowed range
1-128); excess connections receive `503 Service Unavailable` with
`Retry-After: 1`. Each accepted socket has a finite I/O timeout (default 10
seconds, maximum 120 seconds). A client that stops sending bytes cannot retain
a worker beyond this idle timeout. It is not an absolute request deadline: a
slow-trickle client may still occupy one of the bounded slots. These controls
bound local handler resource use; they are not per-principal rate limits or
distributed denial-of-service protection.

## Deployment and limitations

Compose this transport with `OidcTenantPrincipalSource`, a production token
verifier, an authoritative membership resolver, and a session-status validator. The membership resolver must reflect current approved membership state (including revocation) on each authorization decision; a cache introduces a corresponding revocation delay. Member revocation clears governance permissions but does not independently terminate an external identity-provider session.
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
field rejection, loopback-only binding, bounded concurrency, overload response,
stalled-request timeout recovery, and owner-only member revocation with permission clearing and cascading credential-registration revocation. These are transport tests using
injected test verifiers and SQLite, not evidence of a deployed identity provider,
database isolation, or live trading authorization.

## Production admission gate

Server construction now rejects a governance facade unless its
`production_ready` property is exactly true. The explicit
`allow_nonproduction=True` escape hatch exists for isolated tests and local
development only; it must not be enabled in a deployed environment. The current
PostgreSQL governance adapter intentionally reports non-production-ready because
its database tenant context remains caller-settable rather than authenticated by
the database connection identity. Consequently the current runtime composition
cannot yet start this API in production mode. Member revocation is exposed as an
owner-only operation and atomically revokes the member's pending/approved
credentials in the same repository transaction.
