# Phase 361 - Trusted tenant authorization boundary

## Scope
Production-mode Delta account registry operations now require an injected tenant authorization provider. The provider must be explicitly declared production-ready and expose `authorize_tenant(tenant_id)`. The implementation contract requires it to compare the requested tenant against the authenticated server-side principal established by trusted middleware; a caller-supplied tenant string alone is not proof of identity.

## Enforcement
- Production admission fails closed when the authorization provider is missing, undeclared, or incomplete.
- Registration, rotation, key rewrapping, listing, deletion, read-only session creation, and provider-identity binding authorize the tenant before accessing stored account data or encrypting credentials.
- Authorization exceptions, denials, and truthy non-boolean values are rejected with redacted errors.
- Existing read-only sessions re-check tenant authorization on each guarded operation, so revocation can invalidate an active session.
- Non-production/local workflows retain their existing compatibility behavior unless an authorizer is explicitly injected.

## Limits
This phase supplies an enforcement interface, not a complete identity provider. A deployment must integrate its authenticated principal/session middleware and independently review tenant membership, role/permission policy, session revocation, and service-to-service identity. The test authorizer is deliberately a test double and is not production evidence. PostgreSQL and credential-provider admission remain separately gated; live trading remains disarmed and production readiness remains HOLD.
