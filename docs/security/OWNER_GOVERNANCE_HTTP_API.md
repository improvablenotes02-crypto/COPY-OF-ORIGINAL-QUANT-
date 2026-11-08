# Owner governance HTTP API

## Capability

The owner-governance state machine now has a dedicated loopback HTTP transport
that authenticates every mutation through a verified OIDC bearer token. It
binds that token only for the request and delegates identity, tenant membership,
expiry, and active-session checks to the existing trusted principal and
authenticated governance adapters.

Routes:

- `GET /v1/tenants/{tenant}/members` — owner-only member list with status and permissions.
- `GET /v1/tenants/{tenant}/credentials` — owner-only credential approval queue; account, submitter, status, and timestamps only. Credential fingerprints remain internal for exact approval matching.

- `POST /v1/tenants/{tenant}/members` — owner invites a member (PENDING).
- `POST /v1/tenants/{tenant}/members/{subject}/decision` — owner approves or rejects.
- `DELETE /v1/tenants/{tenant}/members/{subject}` — owner revokes an approved member, clears permissions, and atomically revokes that member's pending and approved credential registrations; the configured owner cannot revoke their own identity.
- `POST /v1/tenants/{tenant}/credentials` — approved member submits Delta API credentials to the encrypted vault for owner approval.
- `POST /v1/tenants/{tenant}/credentials/{credential}/decision` — owner approves/rejects.
- `DELETE /v1/tenants/{tenant}/credentials/{credential}` — owner revokes an approved credential.

The API accepts either the legacy metadata-only migration shape or the raw Delta submission shape (`label`, `region`, `environment`, `api_key`, `api_secret`). For raw submissions, it writes secrets only through the injected encrypted Delta registry, then creates a pending owner-approval record. Secrets are never returned, logged, or stored in governance audit metadata. Unrelated fields, including caller-supplied actor IDs and roles, are rejected.
Responses are non-cacheable; request logging is disabled; internal verifier and
persistence exceptions are not echoed. A missing, duplicated, or syntactically malformed bearer header is
401; bearer credentials must contain one RFC 6750 token value (no embedded
whitespace, comma-combined values, or extra credentials). A token that fails verification or fails the authenticated tenant/owner
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
test/development only. PostgreSQL production admission still depends on deployed
per-tenant logins, least-privilege roles, trusted tenant DSN routing, TLS,
production identity/session adapters, encryption/KMS, and durable background-job
storage. The authenticated PostgreSQL tenant-login design is implemented and
integration-tested, but deployment evidence is still required; this API therefore
does not certify production readiness.

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
development only; it must not be enabled in a deployed environment. The PostgreSQL tenant boundary now derives tenant identity from the authenticated
`session_user` mapping rather than a caller-controlled setting, and the integration
tests cover unmapped logins and cross-tenant access denial. Production admission
still requires deployment evidence for per-tenant least-privilege logins, trusted
DSN routing, TLS, identity/session adapters, encryption/KMS, durable background
jobs, and operational recovery. Until those deployment controls are certified,
this API does not certify production readiness. Member revocation is exposed as an
owner-only operation and atomically revokes the member's pending/approved
credentials in the same repository transaction.


## Member credential submission

An authenticated, approved tenant member submits Delta credentials through
`POST /v1/tenants/{tenant}/credentials` with exactly these JSON fields:
`label`, `region`, `environment`, `api_key`, and `api_secret`.
The server must be started with a trusted `account_registry` dependency whose
tenant authorizer is bound to the verified request principal. The registry
encrypts and persists the credentials; the API computes the canonical SHA-256
fingerprint and creates a pending owner-approval record tied to the returned
account ID. The response contains only the account ID and `PENDING` status.
If governance submission fails, the API attempts to delete the newly-created
vault record and returns an error. Plaintext credentials are never included in
responses or audit metadata. The legacy metadata-only submission shape remains
available for controlled migration, but cannot create a usable vault account
by itself.

## PostgreSQL tenant-login deployment

Use the [PostgreSQL tenant-login operations runbook](POSTGRES_TENANT_LOGIN_OPERATIONS.md) to provision one non-privileged database login per tenant, maintain the DBA-owned identity map, configure TLS-verified tenant DSNs, and verify spoof resistance. This database boundary is necessary but does not by itself certify production readiness; deployment identity, session revocation, encryption, background-job storage, and operational recovery evidence remain separate admission requirements.


## Minimal owner/member workflow

The workflow is intentionally short. The identity provider must first create or
recognize the member's login so the owner can use that immutable OIDC
`subject_id`; this API does not create passwords or provision identity-provider
accounts.

1. Owner invites the member (`PENDING`).
2. Owner approves the member.
3. Member submits broker API credentials (encrypted in the registry; approval is
   still `PENDING`).
4. Owner reviews the queue and approves or rejects the credential.
5. Only that member can use credentials approved for the tenant. The owner can
   revoke a credential or the member.

Every request requires a verified OIDC bearer token. Replace the placeholders
with deployment values. Do not put real secrets in shell history or shared
terminals; use a secret-input mechanism in production.

Invite a member (owner):
```sh
curl -fsS -X POST "$BASE/v1/tenants/$TENANT/members" \
  -H "Authorization: Bearer $OWNER_TOKEN" -H "Content-Type: application/json" \
  --data '{"subject_id":"'$OIDC_SUBJECT'"}'
```

Approve the member (owner):
```sh
curl -fsS -X POST "$BASE/v1/tenants/$TENANT/members/$OIDC_SUBJECT/decision" \
  -H "Authorization: Bearer $OWNER_TOKEN" -H "Content-Type: application/json" \
  --data '{"approve":true}'
```

Member submits Delta credentials using a protected local file:
```sh
curl -fsS -X POST "$BASE/v1/tenants/$TENANT/credentials" \
  -H "Authorization: Bearer $MEMBER_TOKEN" -H "Content-Type: application/json" \
  --data-binary @delta-credential-request.json
```

The file must contain exactly these fields:
```json
{
  "label": "Primary Delta account",
  "region": "india",
  "environment": "production",
  "api_key": "SUPPLY_SECURELY",
  "api_secret": "SUPPLY_SECURELY"
}
```

Owner reviews pending credentials:
```sh
curl -fsS "$BASE/v1/tenants/$TENANT/credentials" \
  -H "Authorization: Bearer $OWNER_TOKEN"
```

Owner approves a credential using its returned `account_id`:
```sh
curl -fsS -X POST "$BASE/v1/tenants/$TENANT/credentials/ACCOUNT_ID/decision" \
  -H "Authorization: Bearer $OWNER_TOKEN" -H "Content-Type: application/json" \
  --data '{"approve":true}'
```

Use `{"approve":false}` to reject. The owner can revoke a credential with
`DELETE /v1/tenants/{tenant}/credentials/{credential_id}`, or revoke a member
with `DELETE /v1/tenants/{tenant}/members/{subject_id}`. Member revocation also
clears permissions and revokes that member's pending/approved credential
registrations; it does not delete the external identity-provider account.


If member removal returns a nonzero `vault_cleanup_pending`, membership and
credential approvals are already revoked (so access remains disabled), but one
or more encrypted vault deletions need retry. The owner can list the credential
queue, locate each affected `REVOKED` record by its `account_id`/`credential_id`,
and repeat `DELETE /v1/tenants/{tenant}/credentials/{credential_id}`. This
cleanup route is idempotent and can finish deletion after a temporary vault
failure; it never re-approves a credential.
