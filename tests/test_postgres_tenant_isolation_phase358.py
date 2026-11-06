"""Phase 358: verify PostgreSQL RLS boundaries and immutable audit records."""
import os
from pathlib import Path
import psycopg
import pytest

ADMIN=os.getenv("QUANTENGINE_TEST_POSTGRES_ADMIN_DSN")
RUNTIME=os.getenv("QUANTENGINE_TEST_POSTGRES_RUNTIME_DSN")
pytestmark=pytest.mark.skipif(not ADMIN or not RUNTIME,reason="PostgreSQL CI DSNs absent")

def test_tenant_rls_and_audit_immutability():
    sql=Path("migrations/postgres/001_delta_account_registry.sql").read_text()
    with psycopg.connect(ADMIN,autocommit=True) as db:
        db.execute("DROP TABLE IF EXISTS public.delta_credential_rotation_events CASCADE")
        db.execute("DROP TABLE IF EXISTS public.delta_accounts CASCADE")
        db.execute("DROP FUNCTION IF EXISTS public.reject_delta_rotation_mutation() CASCADE")
        db.execute("DROP ROLE IF EXISTS qe_runtime_phase358")
        db.execute("CREATE ROLE qe_runtime_phase358 LOGIN PASSWORD 'qe_runtime_phase358_test' NOSUPERUSER NOBYPASSRLS")
        db.execute(sql); db.execute(sql)
        db.execute("GRANT USAGE ON SCHEMA public TO qe_runtime_phase358")
        db.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON public.delta_accounts,public.delta_credential_rotation_events TO qe_runtime_phase358")
        for aid,tenant in (("a","tenant-a"),("b","tenant-b")):
            db.execute("INSERT INTO public.delta_accounts VALUES (%s,%s,'delta','INDIA','SANDBOX',%s,NULL,'key-v1','AES-256-GCM',%s,1,1,1)",(aid,tenant,tenant,b"ciphertext"))
        db.execute("INSERT INTO public.delta_credential_rotation_events VALUES ('evt','tenant-a','a',1,2,'v1','v2',2,%s,%s)",("0"*64,"a"*64))
    try:
        with psycopg.connect(RUNTIME) as db:
            assert db.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()==(False,False)
            with db.transaction():
                db.execute("SELECT set_config('quantengine.tenant_id',%s,true)",("tenant-a",))
                assert db.execute("SELECT account_id FROM public.delta_accounts").fetchall()==[("a",)]
                assert db.execute("SELECT count(*) FROM public.delta_credential_rotation_events").fetchone()==(1,)
                assert db.execute("UPDATE public.delta_accounts SET label='x' WHERE tenant_id='tenant-b'").rowcount==0
            with db.transaction():
                db.execute("SELECT set_config('quantengine.tenant_id',%s,true)",("tenant-b",))
                assert db.execute("SELECT account_id FROM public.delta_accounts").fetchall()==[("b",)]
                assert db.execute("SELECT count(*) FROM public.delta_credential_rotation_events").fetchone()==(0,)
            with db.transaction():
                db.execute("SELECT set_config('quantengine.tenant_id',%s,true)",("tenant-a",))
                with pytest.raises(psycopg.Error,match="immutable"):
                    with db.transaction():
                        db.execute("UPDATE public.delta_credential_rotation_events SET new_key_id='tampered' WHERE event_id='evt'")
    finally:
        with psycopg.connect(ADMIN,autocommit=True) as db:
            db.execute("DROP ROLE IF EXISTS qe_runtime_phase358")
