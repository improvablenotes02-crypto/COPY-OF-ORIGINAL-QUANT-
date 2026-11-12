"""Phase 370-372: database-authenticated PostgreSQL tenant isolation."""
import os
from pathlib import Path
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

ADMIN = os.getenv("QUANTENGINE_TEST_POSTGRES_ADMIN_DSN")
pytestmark = pytest.mark.skipif(not ADMIN, reason="PostgreSQL admin DSN absent")
ROLE_A, ROLE_B = "qe_phase370_tenant_a", "qe_phase370_tenant_b"
PASSWORD_A, PASSWORD_B = "qe_phase370_a_test_only", "qe_phase370_b_test_only"


def _dsn(role, password):
    return make_conninfo(ADMIN, user=role, password=password)


def test_database_login_identity_cannot_be_spoofed_with_tenant_guc():
    migrations = [
        Path("migrations/postgres/001_delta_account_registry.sql").read_text(),
        Path("migrations/postgres/002_owner_governance.sql").read_text(),
        Path("migrations/postgres/003_authenticated_tenant_identity.sql").read_text(),
    ]
    with psycopg.connect(ADMIN, autocommit=True) as db:
        for table in ("qe_governance_audit", "qe_credential_approvals", "qe_memberships",
                      "delta_credential_rotation_events", "delta_accounts"):
            db.execute(f"DROP TABLE IF EXISTS public.{table} CASCADE")
        for function in ("reject_qe_governance_audit_mutation", "reject_delta_rotation_mutation",
                         "qe_authenticated_tenant_id"):
            db.execute(f"DROP FUNCTION IF EXISTS public.{function}() CASCADE")
        db.execute("DROP TABLE IF EXISTS public.qe_tenant_login_map CASCADE")
        for role in (ROLE_A, ROLE_B):
            if db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                db.execute(f'DROP OWNED BY "{role}"')
                db.execute(f'DROP ROLE "{role}"')
        db.execute(f'CREATE ROLE "{ROLE_A}" LOGIN PASSWORD \'{PASSWORD_A}\' NOSUPERUSER NOBYPASSRLS')
        db.execute(f'CREATE ROLE "{ROLE_B}" LOGIN PASSWORD \'{PASSWORD_B}\' NOSUPERUSER NOBYPASSRLS')
        for sql in migrations:
            db.execute(sql)
        db.execute(
            "INSERT INTO public.qe_tenant_login_map(login_role,tenant_id) VALUES (%s,%s),(%s,%s)",
            (ROLE_A, "tenant-a", ROLE_B, "tenant-b"),
        )
        for role in (ROLE_A, ROLE_B):
            db.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            db.execute(f'GRANT SELECT,INSERT,UPDATE,DELETE ON public.delta_accounts, '
                       f'public.delta_credential_rotation_events, public.qe_memberships, '
                       f'public.qe_credential_approvals, public.qe_governance_audit TO "{role}"')
        db.execute(
            "INSERT INTO public.delta_accounts "
            "(account_id,tenant_id,venue,region,environment,label,key_id,algorithm,ciphertext,"
            "created_at_ns,updated_at_ns,credential_generation) "
            "VALUES ('acct-a','tenant-a','delta','INDIA','SANDBOX','A','k1','AES-256-GCM',%s,1,1,1),"
            "('acct-b','tenant-b','delta','INDIA','SANDBOX','B','k1','AES-256-GCM',%s,1,1,1)",
            (b"synthetic-a", b"synthetic-b"),
        )
        db.execute(
            "INSERT INTO public.qe_memberships "
            "(tenant_id,subject_id,status,permissions_json,created_at_ns,updated_at_ns) "
            "VALUES ('tenant-a','member-a','APPROVED','[]'::jsonb,1,1),"
            "('tenant-b','member-b','APPROVED','[]'::jsonb,1,1)"
        )
    try:
        with psycopg.connect(_dsn(ROLE_A, PASSWORD_A)) as db:
            assert db.execute("SELECT session_user").fetchone()[0] == ROLE_A
            assert db.execute("SELECT public.qe_authenticated_tenant_id()").fetchone()[0] == "tenant-a"
            with db.transaction():
                db.execute("SELECT set_config('quantengine.tenant_id','tenant-b',true)")
                assert db.execute("SELECT account_id FROM public.delta_accounts").fetchall() == [("acct-a",)]
                assert db.execute("SELECT subject_id FROM public.qe_memberships").fetchall() == [("member-a",)]
                # Tenant logins cannot read or mutate the DBA-owned identity map.
                with pytest.raises(psycopg.Error):
                    with db.transaction():
                        db.execute(
                            "INSERT INTO public.qe_tenant_login_map(login_role,tenant_id) "
                            "VALUES ('spoofed-login','tenant-b')"
                        )
                with pytest.raises(psycopg.Error):
                    with db.transaction():
                        db.execute(
                            "INSERT INTO public.delta_accounts "
                            "(account_id,tenant_id,venue,region,environment,label,key_id,algorithm,ciphertext,"
                            "created_at_ns,updated_at_ns,credential_generation) "
                            "VALUES ('spoof','tenant-b','delta','INDIA','SANDBOX','spoof','k1','AES-256-GCM',%s,2,2,1)",
                            (b"synthetic",),
                        )
        with psycopg.connect(_dsn(ROLE_B, PASSWORD_B)) as db:
            assert db.execute("SELECT public.qe_authenticated_tenant_id()").fetchone()[0] == "tenant-b"
            assert db.execute("SELECT account_id FROM public.delta_accounts").fetchall() == [("acct-b",)]
            assert db.execute("SELECT subject_id FROM public.qe_memberships").fetchall() == [("member-b",)]
        # An unmapped database login is denied by NULL RLS predicates.
        with psycopg.connect(ADMIN, autocommit=True) as db:
            db.execute("DELETE FROM public.qe_tenant_login_map WHERE login_role=%s", (ROLE_B,))
        with psycopg.connect(_dsn(ROLE_B, PASSWORD_B)) as db:
            assert db.execute("SELECT public.qe_authenticated_tenant_id()").fetchone()[0] is None
            assert db.execute("SELECT account_id FROM public.delta_accounts").fetchall() == []
            with pytest.raises(psycopg.Error):
                with db.transaction():
                    db.execute(
                        "INSERT INTO public.delta_accounts "
                        "(account_id,tenant_id,venue,region,environment,label,key_id,algorithm,ciphertext,"
                        "created_at_ns,updated_at_ns,credential_generation) "
                        "VALUES ('unmapped','tenant-b','delta','INDIA','SANDBOX','unmapped','k1','AES-256-GCM',%s,3,3,1)",
                        (b"synthetic",),
                    )

        from core.accounts.postgres_delta_account_repository import AuthenticatedPostgreSQLDeltaAccountRepository
        from core.accounts.postgres_owner_governance_repository import AuthenticatedPostgreSQLOwnerGovernanceRepository
        tenant_a_resolver = lambda tenant: _dsn(ROLE_A, PASSWORD_A)
        delta_repo = AuthenticatedPostgreSQLDeltaAccountRepository(tenant_a_resolver)
        assert delta_repo.get("tenant-a", "acct-a").account_id == "acct-a"
        assert delta_repo.get("tenant-a", "acct-b") is None

        # Exercise the authenticated repository's write transaction, not just
        # its tenant-scoped read path. A denied callback must roll back; an
        # approved callback may bind the identity while the row lock is held.
        from core.accounts.delta_account_registry import AccountScopeError
        with pytest.raises(AccountScopeError, match="authorization is no longer valid"):
            delta_repo.bind_provider_identity(
                "tenant-a", "acct-a", "delta-user-a",
                expected_generation=1, expected_updated_at_ns=1,
                authorization_check=lambda: False,
            )
        assert delta_repo.get("tenant-a", "acct-a").provider_account_id is None
        delta_repo.bind_provider_identity(
            "tenant-a", "acct-a", "delta-user-a",
            expected_generation=1, expected_updated_at_ns=1,
            authorization_check=lambda: True,
        )
        assert delta_repo.get("tenant-a", "acct-a").provider_account_id == "delta-user-a"
        with pytest.raises(Exception):
            delta_repo.get("tenant-b", "acct-b")
        governance_repo = AuthenticatedPostgreSQLOwnerGovernanceRepository(tenant_a_resolver)
        assert governance_repo.membership("tenant-a", "member-a").subject_id == "member-a"

        # Exercise the complete owner/member credential lifecycle through the
        # database-authenticated repository, not only its read path.
        governance_repo.invite(
            "tenant-a", "member-created", ("read",), "owner-a", 10
        )
        assert governance_repo.membership("tenant-a", "member-created").status == "PENDING"
        governance_repo.decide_membership(
            "tenant-a", "member-created", "APPROVED", ("read",), "owner-a", 11
        )
        governance_repo.submit_credential(
            "tenant-a", "credential-created", "member-created",
            "delta-account-created", "d" * 64, 12
        )
        assert governance_repo.credential(
            "tenant-a", "credential-created"
        ).status == "PENDING"
        governance_repo.decide_credential(
            "tenant-a", "credential-created", "APPROVED", "owner-a", 13
        )
        assert governance_repo.credential(
            "tenant-a", "credential-created"
        ).status == "APPROVED"

        # Repeated timestamps must still produce a strictly ordered,
        # verifiable append-only audit chain.
        governance_repo.invite(
            "tenant-a", "same-time-one", ("read",), "owner-a", 20
        )
        governance_repo.invite(
            "tenant-a", "same-time-two", ("read",), "owner-a", 20
        )
        audit_events = governance_repo.audit_events("tenant-a")
        assert all(
            current["occurred_at_ns"] > previous["occurred_at_ns"]
            for previous, current in zip(audit_events, audit_events[1:])
        )
        assert all(
            current["previous_hash"] == previous["event_hash"]
            for previous, current in zip(audit_events, audit_events[1:])
        )

        # The resolver is deliberately pinned to tenant A's database login.
        # A caller cannot switch it to tenant B by choosing another tenant ID.
        with pytest.raises(RuntimeError, match="operation failed"):
            governance_repo.invite(
                "tenant-b", "spoofed-member", ("read",), "owner-a", 14
            )
        with psycopg.connect(_dsn(ROLE_B, PASSWORD_B)) as db:
            assert db.execute(
                "SELECT subject_id FROM public.qe_memberships WHERE subject_id='spoofed-member'"
            ).fetchall() == []
            assert db.execute(
                "SELECT credential_id FROM public.qe_credential_approvals "
                "WHERE credential_id='credential-created'"
            ).fetchall() == []
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as db:
            db.execute("DELETE FROM public.qe_tenant_login_map WHERE login_role IN (%s,%s)", (ROLE_A, ROLE_B))
            for role in (ROLE_A, ROLE_B):
                if db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                    db.execute(f'DROP OWNED BY "{role}"')
                    db.execute(f'DROP ROLE "{role}"')
