# Phases 370–372: authenticated PostgreSQL tenant boundary

PostgreSQL RLS tenant identity is derived from `session_user` through
`public.qe_tenant_login_map`, never from a request parameter or caller-settable
custom setting. The mapping table is private to the trusted migration/DBA owner.
Runtime roles must be tenant-specific LOGIN roles with NOSUPERUSER and
NOBYPASSRLS, and must not own protected tables or assume another tenant role.

A DBA provisions one login per tenant and inserts its exact role-to-tenant
mapping using a privileged migration connection. Unmapped roles resolve to
NULL and therefore see or write no tenant rows. Runtime roles receive no
mapping-table or role-management privileges.

Apply migrations 001 and 002, then 003 with the trusted migration identity.
Provision and verify tenant roles before routing tenant traffic. Existing
shared runtime logins are intentionally unmapped and fail closed after 003.
Do not retain the old caller-settable GUC policy as a fallback.

The integration test exercises both credential and owner-governance RLS,
including attempts to spoof the tenant GUC and write another tenant's rows.
This does not certify production role provisioning, secret separation, or
application connection-pool routing. Production readiness remains HOLD and
live execution remains disabled until those controls are independently proven.
