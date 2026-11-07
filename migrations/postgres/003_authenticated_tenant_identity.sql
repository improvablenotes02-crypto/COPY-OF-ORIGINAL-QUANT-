-- Phase 370: bind RLS tenant identity to the authenticated PostgreSQL login.
-- Provision and map tenant-specific LOGIN roles through a trusted DBA process.
CREATE TABLE IF NOT EXISTS public.qe_tenant_login_map (
    login_role NAME PRIMARY KEY,
    tenant_id TEXT NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON public.qe_tenant_login_map FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.qe_authenticated_tenant_id()
RETURNS TEXT LANGUAGE SQL STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
    SELECT tenant_id FROM public.qe_tenant_login_map
    WHERE login_role = session_user::name
$function$;
REVOKE ALL ON FUNCTION public.qe_authenticated_tenant_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.qe_authenticated_tenant_id() TO PUBLIC;

-- Unmapped identities return NULL (deny all). Runtime roles cannot modify the map.
DROP POLICY IF EXISTS delta_accounts_tenant_scope ON public.delta_accounts;
CREATE POLICY delta_accounts_tenant_scope ON public.delta_accounts FOR ALL TO PUBLIC
 USING (tenant_id = public.qe_authenticated_tenant_id())
 WITH CHECK (tenant_id = public.qe_authenticated_tenant_id());
DROP POLICY IF EXISTS delta_rotation_tenant_scope ON public.delta_credential_rotation_events;
CREATE POLICY delta_rotation_tenant_scope ON public.delta_credential_rotation_events FOR ALL TO PUBLIC
 USING (tenant_id = public.qe_authenticated_tenant_id())
 WITH CHECK (tenant_id = public.qe_authenticated_tenant_id());
DROP POLICY IF EXISTS qe_memberships_tenant_scope ON public.qe_memberships;
CREATE POLICY qe_memberships_tenant_scope ON public.qe_memberships FOR ALL TO PUBLIC
 USING (tenant_id = public.qe_authenticated_tenant_id())
 WITH CHECK (tenant_id = public.qe_authenticated_tenant_id());
DROP POLICY IF EXISTS qe_credentials_tenant_scope ON public.qe_credential_approvals;
CREATE POLICY qe_credentials_tenant_scope ON public.qe_credential_approvals FOR ALL TO PUBLIC
 USING (tenant_id = public.qe_authenticated_tenant_id())
 WITH CHECK (tenant_id = public.qe_authenticated_tenant_id());
DROP POLICY IF EXISTS qe_governance_audit_tenant_scope ON public.qe_governance_audit;
CREATE POLICY qe_governance_audit_tenant_scope ON public.qe_governance_audit FOR ALL TO PUBLIC
 USING (tenant_id = public.qe_authenticated_tenant_id())
 WITH CHECK (tenant_id = public.qe_authenticated_tenant_id());
