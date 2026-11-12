# PostgreSQL tenant-login operations

## Purpose and admission boundary

QuantEngine uses a database-authenticated tenant identity for shared PostgreSQL
tables. The tenant identity is derived from PostgreSQL `session_user`, mapped
by `public.qe_tenant_login_map`; it is not derived from the request tenant
header, a transaction-local custom setting, or a caller-supplied SQL parameter.

Apply migrations in order:

1. `001_delta_account_registry.sql`
2. `002_owner_governance.sql`
3. `003_authenticated_tenant_identity.sql`

Run migrations as a dedicated schema/migration administrator. Never run the
application as the migration owner, a superuser, or a role with
`BYPASSRLS`.

## Provision one login per tenant

For each tenant, create a distinct PostgreSQL LOGIN role. Use a DBA-managed
secret workflow; do not place passwords in migration files, shell history,
source control, logs, or deployment manifests.

Example administrative SQL (replace identifiers with validated deployment
values):

```sql
CREATE ROLE qe_tenant_acme LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE quantengine TO qe_tenant_acme;
GRANT USAGE ON SCHEMA public TO qe_tenant_acme;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON public.delta_accounts,
       public.delta_credential_rotation_events,
       public.qe_memberships,
       public.qe_credential_approvals,
       public.qe_governance_audit
    TO qe_tenant_acme;
INSERT INTO public.qe_tenant_login_map(login_role, tenant_id)
VALUES ('qe_tenant_acme', 'tenant-acme');
```

Set or rotate the login password through the database's interactive
`\\password qe_tenant_acme` command or an approved secret manager workflow.
Do not use a password literal in the SQL above. The login map is DBA-owned:
application roles must have no INSERT, UPDATE, DELETE, TRUNCATE, or ownership
privilege on it, and must not be members of the migration/admin roles.

Grant only the table privileges required by the application. The migration
installs row-level security policies whose tenant predicate calls
`qe_authenticated_tenant_id()`. Keep FORCE ROW LEVEL SECURITY enabled on
tenant tables; do not grant BYPASSRLS, table ownership, or superuser privileges
to tenant logins. Do not grant one tenant login membership in another tenant
login. Each login must map to exactly one tenant.

## Configure the application

The deployment-owned tenant DSN resolver must return the dedicated tenant
login DSN for the requested tenant. Keep the mapping in a trusted deployment
configuration or secret manager; never derive role names or DSNs from request
data. The authenticated tenant repository factory requires `sslmode=verify-full`
by default and rejects missing, weaker, or invalid TLS modes before opening a
socket. This mode verifies both the certificate chain and the server hostname.
Do not disable this check in production. The lower-level adapter override exists
only for controlled local integration fixtures and must not be exposed through
deployment configuration. Keep bounded connection timeouts.

The connection adapter verifies that
`qe_authenticated_tenant_id()` equals the requested tenant before yielding a
transaction. A mismatch or database verification failure is denied and
redacted. A caller-settable `quantengine.tenant_id` setting cannot change the
identity because the database function uses `session_user`.

## Post-provision verification

Run these checks as each tenant login:

```sql
SELECT session_user;
SELECT public.qe_authenticated_tenant_id();
SELECT current_setting('quantengine.tenant_id', true);
SELECT rolname, rolsuper, rolbypassrls
FROM pg_roles WHERE rolname = session_user;
```

The authenticated tenant function must return the one configured tenant.
Changing `quantengine.tenant_id` to another tenant must not change visible rows
or permit writes for that tenant. Verify both reads and writes against synthetic
records in a staging database. Also verify that an unmapped login sees no rows
and cannot insert tenant records.

As an administrator, periodically audit the map and role flags:

```sql
SELECT login_role, tenant_id FROM public.qe_tenant_login_map
ORDER BY tenant_id, login_role;
SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb
FROM pg_roles WHERE rolname LIKE 'qe_tenant_%'
ORDER BY rolname;
```

Review changes through the DBA change process. Rotate credentials without
reusing a tenant login for another tenant. On tenant offboarding, disable the
login first, revoke active sessions, remove its mapping, and then follow the
data-retention procedure. Never reassign an existing login name to a different
tenant.

## Production admission

Database-authenticated tenant routing is necessary but not sufficient for
production admission. The runtime must also use a production OIDC verifier,
authoritative live membership resolver, session-revocation validator, durable
production background-job store, approved encryption/key-management provider,
and a tested deployment-owned DSN resolver. Validate backup/restore, monitoring,
network restrictions, key rotation, and incident response in the target
environment.

The repository adapters intentionally remain `production_ready = False`
until that deployment evidence and provisioning lifecycle are certified.
Do not override the flag or enable the non-production API escape hatch in a
deployed environment. Live order execution remains separately disarmed.
