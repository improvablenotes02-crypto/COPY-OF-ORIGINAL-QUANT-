# Phases 373–375: tenant-bound application repository admission

## Phase 373 — trusted tenant connection routing

`TenantBoundPostgreSQLConnection` accepts only a server-owned resolver. The
resolver receives the requested tenant and returns a tenant-specific PostgreSQL
DSN. Each connection executes `SELECT public.qe_authenticated_tenant_id()`
inside its transaction and compares the database-authenticated result with the
requested tenant before yielding. No custom GUC is set or read. Missing
mappings, mismatches, resolver failures, and database errors fail closed.
Resolvers must not accept DSNs or database role names from request data, member
profiles, JWT claims, or other caller-controlled input.

## Phase 374 — authenticated repository adapters

`AuthenticatedPostgreSQLDeltaAccountRepository` and
`AuthenticatedPostgreSQLOwnerGovernanceRepository` reuse established
repository operations with the tenant-bound connection boundary. Identity is
checked on every connection. These adapters report tenant isolation as
enforced, but retain `production_ready = False`: role provisioning, credential
encryption/key management, deployment secret separation, operational recovery,
and full production evidence remain separate gates. Legacy adapters remain
non-production-ready and must not be used with migration 003 in production.

## Phase 375 — adversarial verification

Unit tests prove tenant-specific DSN resolution, identity equality, rejection
of NULL/empty/mismatched identities, and fail-closed handling of resolver or
database errors. PostgreSQL integration tests exercise both authenticated
adapters with tenant-specific LOGIN roles and deliberately route a tenant-B
request through tenant A's login to prove rejection.

## Deployment status

Do not apply migration 003 until all application adapters and background
workers use tenant-specific identities. Existing shared runtime logins are
intentionally unmapped and lose access. Never use a shared-login fallback,
enable live execution, or automatically resend ambiguous orders. Overall
QuantEngine production readiness remains HOLD.
