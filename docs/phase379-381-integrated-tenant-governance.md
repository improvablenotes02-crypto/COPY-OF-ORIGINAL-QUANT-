# Phases 379–381: integrated tenant governance runtime

## Phase 379 — trusted governance composition root
Added `AuthenticatedTenantGovernanceRuntime`, composing the server-configured
owner subject, trusted principal source, active-session validator, authenticated
PostgreSQL governance repository, tenant-membership facade, and owner-only
domain service. Request callers cannot supply actor IDs. Cross-tenant calls fail
before persistence.

## Phase 380 — credential approval shares the guarded repository
The runtime exposes an `OwnerGovernanceDeltaCredentialApprovalProvider` backed
by the same tenant-authorized repository. Approval checks are bound to the
current authenticated tenant/session and exact account plus credential
fingerprint. Pending credentials remain denied; owner approval is required.

## Phase 381 — live revocation and session revalidation
Approval state is read for each check rather than cached. Owner revocation is
observed by the existing provider; inactive sessions block governance mutations
and credential approval lookups. Tests use a deterministic local repository
double; they do not claim PostgreSQL deployment certification.

## Explicit limits
This composition is not wired into the monitoring HTTP API: its existing bearer
control token is not an OIDC tenant-authentication layer. Do not expose owner
governance routes there until verified OIDC middleware and session revocation
storage are integrated. The PostgreSQL adapter remains `production_ready=False`;
migration 003 still requires provisioned tenant database identities. Live
execution remains disarmed and production readiness HOLD.
