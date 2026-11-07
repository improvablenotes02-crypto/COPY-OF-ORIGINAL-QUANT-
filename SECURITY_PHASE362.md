# Phase 362 - Request-scoped tenant authorization

## Security boundary

The request-scoped adapter binds an immutable principal to Python execution
context and checks tenant membership, expiry, and server-side session status
before a tenant-scoped registry operation. Context variables isolate concurrent
async tasks and the context manager restores the prior value in a `finally`
path.

## Mandatory integration requirements

- Only trusted server authentication middleware may call
  `bind_authenticated_principal`.
- Never build a principal from request JSON, query parameters, unvalidated
  headers, or caller-supplied tenant IDs.
- Middleware must validate issuer, signature, audience, not-before and expiry
  claims, and map the authenticated subject to server-controlled membership.
- The session validator must check authoritative server-side session state and
  revocation on each protected operation.
- Both adapters must explicitly declare `production_ready = True` only after
  real implementations and deployment configuration have been reviewed.
- The default context-variable source is deliberately not production-ready.
  This module does not implement JWT/OIDC validation, passwords, API-key
  authentication, identity-provider connectivity, or cross-process propagation.

## Operational status

Phase 362 provides an adapter contract and fail-closed behavior. It does not
certify production multi-user access or authorize live trading. Production
readiness remains HOLD until real authentication middleware, identity and
session providers, tenant-membership storage, deployment controls, and
end-to-end security tests are integrated and independently reviewed. Live
execution remains disarmed.
