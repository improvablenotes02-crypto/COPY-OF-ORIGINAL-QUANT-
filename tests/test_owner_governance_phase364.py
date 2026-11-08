"""Phase 364: owner-controlled membership and API credential approval."""
import pytest
from core.accounts.owner_governance import (
    GovernanceConflictError, OwnerAuthorizationError, OwnerGovernance,
    SQLiteOwnerGovernanceRepository,
)


@pytest.fixture
def setup(tmp_path):
    repo=SQLiteOwnerGovernanceRepository(tmp_path/"governance.sqlite3")
    service=OwnerGovernance(repo,owner_subject_id="owner-1",clock=lambda:123456)
    yield service,repo
    repo.close()


def test_only_owner_can_invite_or_decide_membership(setup):
    service,repo=setup
    with pytest.raises(OwnerAuthorizationError):
        service.invite_member(actor_id="member-1",tenant_id="t1",subject_id="member-2")
    service.invite_member(actor_id="owner-1",tenant_id="t1",subject_id="member-1",permissions=("read",))
    assert repo.membership("t1","member-1").status=="PENDING"
    with pytest.raises(OwnerAuthorizationError):
        service.decide_member(actor_id="member-1",tenant_id="t1",subject_id="member-1",approve=True)
    service.decide_member(actor_id="owner-1",tenant_id="t1",subject_id="member-1",approve=True,permissions=("read",))
    assert repo.membership("t1","member-1").permissions==("read",)


def test_unapproved_member_cannot_submit_credentials(setup):
    service,repo=setup
    with pytest.raises(OwnerAuthorizationError):
        service.submit_credential(actor_id="member-1",tenant_id="t1",credential_id="c1",
                                  account_id="a1",fingerprint="a"*64)
    service.invite_member(actor_id="owner-1",tenant_id="t1",subject_id="member-1")
    with pytest.raises(OwnerAuthorizationError):
        service.submit_credential(actor_id="member-1",tenant_id="t1",credential_id="c1",
                                  account_id="a1",fingerprint="a"*64)
    service.decide_member(actor_id="owner-1",tenant_id="t1",subject_id="member-1",approve=True)
    service.submit_credential(actor_id="member-1",tenant_id="t1",credential_id="c1",
                              account_id="a1",fingerprint="a"*64)
    assert repo.credential("t1","c1").status=="PENDING"
    assert service.credential_is_approved(tenant_id="t1",credential_id="c1") is False


def test_only_owner_approves_credentials_and_approval_is_one_shot(setup):
    service,repo=setup
    service.submit_credential(actor_id="owner-1",tenant_id="t1",credential_id="c1",
                              account_id="a1",fingerprint="b"*64)
    with pytest.raises(OwnerAuthorizationError):
        service.decide_credential(actor_id="owner-1x",tenant_id="t1",credential_id="c1",approve=True)
    service.decide_credential(actor_id="owner-1",tenant_id="t1",credential_id="c1",approve=True)
    assert service.credential_is_approved(tenant_id="t1",credential_id="c1") is True
    with pytest.raises(GovernanceConflictError):
        service.decide_credential(actor_id="owner-1",tenant_id="t1",credential_id="c1",approve=False)


def test_tenant_scope_and_no_secret_material_in_audit(setup):
    service,repo=setup
    service.submit_credential(actor_id="owner-1",tenant_id="tenant-a",credential_id="cred-a",
                              account_id="acct-a",fingerprint="c"*64)
    assert repo.credential("tenant-b","cred-a") is None
    events=repo.audit_events("tenant-a")
    assert len(events)==1
    assert events[0]["action"]=="CREDENTIAL_SUBMITTED"
    assert "api_secret" not in str(events).lower()
    assert "api_key" not in str(events).lower()


def test_audit_chain_remains_monotonic_when_clock_repeats(setup):
    service, repo = setup
    service.invite_member(
        actor_id="owner-1", tenant_id="tenant-a", subject_id="member-a"
    )
    service.invite_member(
        actor_id="owner-1", tenant_id="tenant-a", subject_id="member-b"
    )
    events = repo.audit_events("tenant-a")
    assert len(events) == 2
    assert events[1]["occurred_at_ns"] > events[0]["occurred_at_ns"]
    assert events[1]["previous_hash"] == events[0]["event_hash"]


def test_owner_identity_is_required_and_sqlite_never_production_ready(tmp_path):
    repo=SQLiteOwnerGovernanceRepository(tmp_path/"g.sqlite3")
    with pytest.raises(ValueError):
        OwnerGovernance(repo,owner_subject_id=" ")
    service=OwnerGovernance(repo,owner_subject_id="owner")
    assert service.production_ready is False
    repo.close()


def test_invalid_permissions_and_fingerprint_rejected(setup):
    service,_=setup
    with pytest.raises(ValueError):
        service.invite_member(actor_id="owner-1",tenant_id="t",subject_id="u",permissions=("owner",))
    with pytest.raises(ValueError):
        service.submit_credential(actor_id="owner-1",tenant_id="t",credential_id="c",
                                  account_id="a",fingerprint="not-a-hash")


def test_credential_rejection_is_terminal(setup):
    service,repo=setup
    service.submit_credential(actor_id="owner-1",tenant_id="t",credential_id="c",
                              account_id="a",fingerprint="d"*64)
    service.decide_credential(actor_id="owner-1",tenant_id="t",credential_id="c",approve=False)
    assert repo.credential("t","c").status=="REJECTED"
    assert not service.credential_is_approved(tenant_id="t",credential_id="c")
