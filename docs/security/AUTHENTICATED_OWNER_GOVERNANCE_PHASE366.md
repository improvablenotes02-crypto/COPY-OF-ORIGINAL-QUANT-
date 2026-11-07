# Phase 366 — authenticated owner governance and honest tenant-boundary admission

## Objective

Ensure request-facing membership and credential-approval operations derive the actor from a trusted authenticated principal, rather than accepting an actor identifier supplied by a caller. Withdraw the stronger tenant-isolation claim from PostgreSQL adapters whose RLS policy depends on a caller-settable custom GUC.

## Authenticated owner facade

`AuthenticatedOwnerGovernance` is the request-facing facade. Its methods do not accept `actor_id`. They obtain an `AuthenticatedPrincipal` from an injected `TrustedPrincipalSource`, require the requested tenant to be in the principal's server-resolved tenant set, reject expired principals, and require an active session through an injected `SessionStatusValidator`.

The low-level `OwnerGovernance` service remains an internal state-machine/persistence facade. It accepts an actor identifier because it is called by the authenticated adapter; it is deliberately never marked production-ready by itself. HTTP/API handlers must not forward request-body or query-string actor identifiers to it.

The existing owner policy remains unchanged: only the configured owner can invite or approve/reject members and approve/reject credentials; a member must be approved before submitting credential metadata. API key/secret material is not accepted or stored by this governance workflow; only a credential identifier, account identifier, and SHA-256 fingerprint are recorded.

## PostgreSQL RLS admission correction

The Phase 358 and Phase 365 policies compare `tenant_id` with `current_setting('quantengine.tenant_id', true)`. The repository sets this custom GUC using `set_config` on the same runtime database role. PostgreSQL permits that role to set the custom GUC itself, so a process holding the runtime DSN can change the tenant context. The Phase 358 integration test itself demonstrates this by using one runtime login and explicitly switching the GUC between tenant A and tenant B.

That behavior provides transaction-local scoping and protects against accidental connection-context leakage, but it is not a database-authenticated tenant boundary against malicious SQL or a compromised runtime role. Accordingly, both PostgreSQL repositories now declare `tenant_isolation_enforced = False`. Their `production_ready` flags remain false, and the Delta registry's production-security admission must reject them.

A follow-on phase must bind tenant identity to a database-authenticated principal (for example, a tenant-specific login role mapped through immutable `session_user` identity, with no ability for the shared runtime login to assume other tenant roles), or another independently verified design. It must include an adversarial test proving one tenant's runtime database identity cannot change context and read or mutate another tenant's rows.

## Evidence and limitations

- Added adversarial tests for caller-supplied actor spoofing, non-owner approval, tenant mismatch, expired principals, inactive sessions, and missing principals.
- Added admission tests ensuring GUC-based PostgreSQL repositories do not claim enforced tenant isolation.
- Runtime CI includes the new test module; strict manifest coverage is updated.
- Tests use deterministic fakes and SQLite for the new authenticated facade. No production OIDC issuer, session store, tenant-specific DB identity, or live account is connected here.
- No broker credentials or real API key material are introduced. No live orders are submitted.

**Certification status: Phase 366 is a scoped security improvement, not production authorization or tenant-isolation certification. Overall status remains NOT PRODUCTION READY / HOLD.**
