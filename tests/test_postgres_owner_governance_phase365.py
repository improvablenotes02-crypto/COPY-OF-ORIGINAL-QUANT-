"""Phase 365 PostgreSQL governance persistence and RLS tests."""
import os
from pathlib import Path
import psycopg, pytest
from core.accounts.owner_governance import OwnerGovernance,OwnerAuthorizationError,GovernanceConflictError
from core.accounts.postgres_owner_governance_repository import PostgreSQLOwnerGovernanceRepository
ADMIN=os.getenv("QUANTENGINE_TEST_POSTGRES_ADMIN_DSN"); RUNTIME=os.getenv("QUANTENGINE_TEST_POSTGRES_RUNTIME_DSN")
pytestmark=pytest.mark.skipif(not ADMIN or not RUNTIME,reason="PostgreSQL CI DSNs absent")
@pytest.fixture
def service():
    sql=Path("migrations/postgres/002_owner_governance.sql").read_text()
    with psycopg.connect(ADMIN,autocommit=True) as db:
        db.execute("DROP TABLE IF EXISTS public.qe_credential_approvals CASCADE"); db.execute("DROP TABLE IF EXISTS public.qe_governance_audit CASCADE"); db.execute("DROP TABLE IF EXISTS public.qe_memberships CASCADE"); db.execute("DROP FUNCTION IF EXISTS public.reject_qe_governance_audit_mutation() CASCADE")
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname='qe_runtime_phase358'").fetchone(): db.execute("DROP OWNED BY qe_runtime_phase358"); db.execute("DROP ROLE qe_runtime_phase358")
        db.execute("CREATE ROLE qe_runtime_phase358 LOGIN PASSWORD 'qe_runtime_phase358_test' NOSUPERUSER NOBYPASSRLS"); db.execute(sql)
        db.execute("GRANT USAGE ON SCHEMA public TO qe_runtime_phase358"); db.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON public.qe_memberships,public.qe_credential_approvals,public.qe_governance_audit TO qe_runtime_phase358")
    try: yield OwnerGovernance(PostgreSQLOwnerGovernanceRepository(RUNTIME),owner_subject_id="owner-1",clock=lambda:123456)
    finally:
        with psycopg.connect(ADMIN,autocommit=True) as db:
            if db.execute("SELECT 1 FROM pg_roles WHERE rolname='qe_runtime_phase358'").fetchone(): db.execute("DROP OWNED BY qe_runtime_phase358"); db.execute("DROP ROLE qe_runtime_phase358")
def test_durable_membership_and_credential_approval(service):
    service.invite_member(actor_id="owner-1",tenant_id="tenant-a",subject_id="member-1",permissions=("read",))
    with pytest.raises(OwnerAuthorizationError): service.decide_member(actor_id="member-1",tenant_id="tenant-a",subject_id="member-1",approve=True)
    service.decide_member(actor_id="owner-1",tenant_id="tenant-a",subject_id="member-1",approve=True)
    service.submit_credential(actor_id="member-1",tenant_id="tenant-a",credential_id="cred-1",account_id="acct-1",fingerprint="a"*64)
    assert not service.credential_is_approved(tenant_id="tenant-a",credential_id="cred-1")
    service.decide_credential(actor_id="owner-1",tenant_id="tenant-a",credential_id="cred-1",approve=True)
    restarted=OwnerGovernance(PostgreSQLOwnerGovernanceRepository(RUNTIME),owner_subject_id="owner-1")
    assert restarted.credential_is_approved(tenant_id="tenant-a",credential_id="cred-1") and restarted.production_ready is False
def test_tenant_rls_and_audit_immutability(service):
    service.submit_credential(actor_id="owner-1",tenant_id="tenant-a",credential_id="cred-a",account_id="acct-a",fingerprint="b"*64)
    service.submit_credential(actor_id="owner-1",tenant_id="tenant-b",credential_id="cred-b",account_id="acct-b",fingerprint="c"*64)
    assert not service.credential_is_approved(tenant_id="tenant-a",credential_id="cred-b")
    events=service._repository.audit_events("tenant-a")
    assert len(events)==1 and events[0]["actor_id"]=="owner-1" and "api_secret" not in str(events).lower()
    with psycopg.connect(ADMIN) as db:
        with pytest.raises(psycopg.Error,match="immutable"):
            with db.transaction(): db.execute("UPDATE public.qe_governance_audit SET action='tampered' WHERE tenant_id='tenant-a'")
def test_member_requires_approval_and_rejection_is_terminal(service):
    service.invite_member(actor_id="owner-1",tenant_id="tenant-a",subject_id="member-2")
    with pytest.raises(OwnerAuthorizationError): service.submit_credential(actor_id="member-2",tenant_id="tenant-a",credential_id="cred-2",account_id="acct-2",fingerprint="d"*64)
    service.decide_member(actor_id="owner-1",tenant_id="tenant-a",subject_id="member-2",approve=True)
    service.submit_credential(actor_id="member-2",tenant_id="tenant-a",credential_id="cred-2",account_id="acct-2",fingerprint="d"*64)
    service.decide_credential(actor_id="owner-1",tenant_id="tenant-a",credential_id="cred-2",approve=False)
    with pytest.raises(GovernanceConflictError): service.decide_credential(actor_id="owner-1",tenant_id="tenant-a",credential_id="cred-2",approve=True)


def test_delta_approval_adapter_uses_exact_postgres_tuple_and_live_revocation(service):
    from core.accounts.delta_credential_approval import (
        OwnerGovernanceDeltaCredentialApprovalProvider,
    )
    repository = service._repository
    provider = OwnerGovernanceDeltaCredentialApprovalProvider(repository)
    service.submit_credential(
        actor_id="owner-1", tenant_id="tenant-a", credential_id="credential-delta",
        account_id="delta-account", fingerprint="e" * 64,
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="delta-account", fingerprint="e" * 64
    )
    service.decide_credential(
        actor_id="owner-1", tenant_id="tenant-a",
        credential_id="credential-delta", approve=True,
    )
    assert provider.is_approved(
        tenant_id="tenant-a", account_id="delta-account", fingerprint="e" * 64
    )
    assert not provider.is_approved(
        tenant_id="tenant-b", account_id="delta-account", fingerprint="e" * 64
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="other-account", fingerprint="e" * 64
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="delta-account", fingerprint="f" * 64
    )
    service.revoke_credential(
        actor_id="owner-1", tenant_id="tenant-a", credential_id="credential-delta"
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="delta-account", fingerprint="e" * 64
    )


def test_owner_can_revoke_member_and_clear_permissions(service):
    service.invite_member(actor_id="owner-1", tenant_id="tenant-a",
                          subject_id="member-revoke", permissions=("read", "trade_paper"))
    service.decide_member(actor_id="owner-1", tenant_id="tenant-a",
                          subject_id="member-revoke", approve=True,
                          permissions=("read", "trade_paper"))
    service.revoke_member(actor_id="owner-1", tenant_id="tenant-a",
                          subject_id="member-revoke")
    member = service._repository.membership("tenant-a", "member-revoke")
    assert member.status == "REVOKED"
    assert member.permissions == ()
    assert any(event["action"] == "MEMBER_REVOKED" for event in service._repository.audit_events("tenant-a"))
