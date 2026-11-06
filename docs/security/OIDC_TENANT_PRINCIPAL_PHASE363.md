# Phase 363 - OIDC verified identity and authoritative tenant membership

## Scope

Phase 363 adds an adapter from a verified OIDC access token to the request
principal contract introduced in Phase 362. Cryptographic verification is
delegated to an injected OIDC/JWT verifier. Tenant membership is resolved
separately from an authoritative server-side membership store.

## Required provider behavior

The access-token verifier must validate the configured issuer, signature,
audience, expiry, not-before claim, allowed signing algorithms, key identifier
and key rotation. It must reject unsigned tokens, algorithm confusion, unknown
issuers/audiences, malformed claims and unavailable signing keys. Use a
maintained OIDC/JWT library and provider-managed JWKS; do not implement JWT
cryptography in this repository adapter.

The membership resolver must query server-controlled membership records by
verified subject. It must not trust tenant IDs from JWT claims, request bodies,
headers, or query parameters. Membership lookup errors fail closed.

The existing Phase 362 session validator remains a separate required check:
the registry authorizer must verify current session/revocation status before
each protected operation.

## Integration boundary and limitations

`bind_access_token` is intended for trusted HTTP authentication middleware
only. It must receive the bearer token extracted from the Authorization header
after request-size and transport controls; it does not itself authenticate a
token. Phase 363 does not select or configure a real identity provider, does
not implement the verifier or membership database, and does not yet wire this
context into the monitoring HTTP server. Those are explicit deployment and
next-phase integration tasks.

Provider adapters may declare `production_ready = True` only after their
issuer/audience/JWKS policy, database isolation, revocation behavior, failure
modes and deployment configuration are reviewed. The included test doubles
are not production evidence. Live execution remains disarmed and production
readiness remains HOLD.
