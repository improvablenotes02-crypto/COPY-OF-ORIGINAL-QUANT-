-- Phase 358: tenant-isolated PostgreSQL credential metadata.
CREATE TABLE IF NOT EXISTS public.delta_accounts (
 account_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
 venue TEXT NOT NULL CHECK (venue='delta'),
 region TEXT NOT NULL CHECK (region IN ('GLOBAL','INDIA')),
 environment TEXT NOT NULL CHECK (environment IN ('PRODUCTION','SANDBOX')),
 label TEXT NOT NULL, provider_account_id TEXT, key_id TEXT NOT NULL,
 algorithm TEXT NOT NULL, ciphertext BYTEA NOT NULL,
 created_at_ns BIGINT NOT NULL, updated_at_ns BIGINT NOT NULL,
 credential_generation BIGINT NOT NULL DEFAULT 1 CHECK (credential_generation>=1),
 UNIQUE (tenant_id,account_id)
);
CREATE INDEX IF NOT EXISTS idx_delta_accounts_tenant
 ON public.delta_accounts(tenant_id,created_at_ns,account_id);
CREATE TABLE IF NOT EXISTS public.delta_credential_rotation_events (
 event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, account_id TEXT NOT NULL,
 previous_generation BIGINT NOT NULL, new_generation BIGINT NOT NULL,
 previous_key_id TEXT NOT NULL, new_key_id TEXT NOT NULL, occurred_at_ns BIGINT NOT NULL,
 previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
 UNIQUE(tenant_id,account_id,new_generation)
);
ALTER TABLE public.delta_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delta_accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE public.delta_credential_rotation_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delta_credential_rotation_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS delta_accounts_tenant_scope ON public.delta_accounts;
CREATE POLICY delta_accounts_tenant_scope ON public.delta_accounts FOR ALL TO PUBLIC
 USING (tenant_id=current_setting('quantengine.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('quantengine.tenant_id',true));
DROP POLICY IF EXISTS delta_rotation_tenant_scope ON public.delta_credential_rotation_events;
CREATE POLICY delta_rotation_tenant_scope ON public.delta_credential_rotation_events FOR ALL TO PUBLIC
 USING (tenant_id=current_setting('quantengine.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('quantengine.tenant_id',true));
CREATE OR REPLACE FUNCTION public.reject_delta_rotation_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'credential rotation audit events are immutable'; END;
$$;
DROP TRIGGER IF EXISTS delta_rotation_no_update ON public.delta_credential_rotation_events;
CREATE TRIGGER delta_rotation_no_update BEFORE UPDATE ON public.delta_credential_rotation_events
 FOR EACH ROW EXECUTE FUNCTION public.reject_delta_rotation_mutation();
DROP TRIGGER IF EXISTS delta_rotation_no_delete ON public.delta_credential_rotation_events;
CREATE TRIGGER delta_rotation_no_delete BEFORE DELETE ON public.delta_credential_rotation_events
 FOR EACH ROW EXECUTE FUNCTION public.reject_delta_rotation_mutation();
