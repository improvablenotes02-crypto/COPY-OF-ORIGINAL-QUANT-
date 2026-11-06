-- Phase 365: PostgreSQL persistence for owner-governed memberships and credential approvals.
CREATE TABLE IF NOT EXISTS public.qe_memberships (
 tenant_id TEXT NOT NULL, subject_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','REVOKED')),
 permissions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
 created_at_ns BIGINT NOT NULL, updated_at_ns BIGINT NOT NULL,
 PRIMARY KEY(tenant_id,subject_id)
);
CREATE INDEX IF NOT EXISTS idx_qe_memberships_subject ON public.qe_memberships(tenant_id,status,subject_id);
CREATE TABLE IF NOT EXISTS public.qe_credential_approvals (
 tenant_id TEXT NOT NULL, credential_id TEXT NOT NULL, subject_id TEXT NOT NULL, account_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
 status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','REVOKED')),
 created_at_ns BIGINT NOT NULL, updated_at_ns BIGINT NOT NULL,
 PRIMARY KEY(tenant_id,credential_id)
);
CREATE INDEX IF NOT EXISTS idx_qe_credentials_account ON public.qe_credential_approvals(tenant_id,account_id,status);
CREATE TABLE IF NOT EXISTS public.qe_governance_audit (
 event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL,
 target_id TEXT NOT NULL, occurred_at_ns BIGINT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qe_governance_audit_tenant ON public.qe_governance_audit(tenant_id,occurred_at_ns,event_id);
ALTER TABLE public.qe_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qe_memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE public.qe_credential_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qe_credential_approvals FORCE ROW LEVEL SECURITY;
ALTER TABLE public.qe_governance_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.qe_governance_audit FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS qe_memberships_tenant_scope ON public.qe_memberships;
CREATE POLICY qe_memberships_tenant_scope ON public.qe_memberships FOR ALL TO PUBLIC USING (tenant_id=current_setting('quantengine.tenant_id',true)) WITH CHECK (tenant_id=current_setting('quantengine.tenant_id',true));
DROP POLICY IF EXISTS qe_credentials_tenant_scope ON public.qe_credential_approvals;
CREATE POLICY qe_credentials_tenant_scope ON public.qe_credential_approvals FOR ALL TO PUBLIC USING (tenant_id=current_setting('quantengine.tenant_id',true)) WITH CHECK (tenant_id=current_setting('quantengine.tenant_id',true));
DROP POLICY IF EXISTS qe_governance_audit_tenant_scope ON public.qe_governance_audit;
CREATE POLICY qe_governance_audit_tenant_scope ON public.qe_governance_audit FOR ALL TO PUBLIC USING (tenant_id=current_setting('quantengine.tenant_id',true)) WITH CHECK (tenant_id=current_setting('quantengine.tenant_id',true));
CREATE OR REPLACE FUNCTION public.reject_qe_governance_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'governance audit is immutable'; END; $$;
DROP TRIGGER IF EXISTS qe_governance_audit_no_update ON public.qe_governance_audit;
CREATE TRIGGER qe_governance_audit_no_update BEFORE UPDATE ON public.qe_governance_audit FOR EACH ROW EXECUTE FUNCTION public.reject_qe_governance_audit_mutation();
DROP TRIGGER IF EXISTS qe_governance_audit_no_delete ON public.qe_governance_audit;
CREATE TRIGGER qe_governance_audit_no_delete BEFORE DELETE ON public.qe_governance_audit FOR EACH ROW EXECUTE FUNCTION public.reject_qe_governance_audit_mutation();
