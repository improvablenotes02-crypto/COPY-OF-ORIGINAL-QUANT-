"""Phase 366: authenticated owner governance and tenant-boundary admission."""
import pytest

from core.accounts.owner_governance import (
    AuthenticatedOwnerGovernance,
    OwnerAuthorizationError,
    OwnerGovernance,
    SQLiteOwnerGovernanceRepository,
)
from core.accounts.postgres_delta_account_repository import PostgreSQLDeltaAccountRepository
from core.accounts.postgres_owner_governance_repository import PostgreSQLOwnerGovernanceRepository
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal


def _principal(subject, *, tenants=("tenant-a",), expires=200.0):
    return AuthenticatedPrincipal(
        subject_id=subject,
        session_id="session-1",
        tenant_ids=frozenset(tenants),
        expires_at_epoch=expires,
    )


class _PrincipalSource:
    production_ready = False

    def __init__(self, principal):
        self.principal = principal

    def current_principal(self):
        return self.principal


class _SessionValidator:
    production_ready = False

    def __init__(self, active=True):
        self.active = active

    def is_session_active(self, principal):
        return self.active


def _build(tmp_path, principal, sessions=None):
    repository = SQLiteOwnerGovernanceRepository(tmp_path / "governance.sqlite3")
    governance = OwnerGovernance(
        repository, owner_subject_id="owner-1", clock=lambda: 123456
    )
    source = _PrincipalSource(principal)
    validator = sessions or _SessionValidator()
    facade = AuthenticatedOwnerGovernance(
        governance, source, validator, clock=lambda: 100.0
    )
    return facade, source, validator, repository


def test_owner_and_member_workflow_uses_only_authenticated_actor(tmp_path):
    facade, source, _sessions, repository = _build(
        tmp_path, _principal("owner-1")
    )
    try:
        facade.invite_member(
            tenant_id="tenant-a", subject_id="member-1", permissions=("read",)
        )
        with pytest.raises(TypeError):
            facade.invite_member(
                actor_id="owner-1", tenant_id="tenant-a", subject_id="spoofed"
            )

        source.principal = _principal("member-1")
        with pytest.raises(OwnerAuthorizationError):
            facade.decide_member(
                tenant_id="tenant-a", subject_id="member-1", approve=True
            )

        source.principal = _principal("owner-1")
        facade.decide_member(
            tenant_id="tenant-a", subject_id="member-1",
            approve=True, permissions=("read",),
        )
        source.principal = _principal("member-1")
        facade.submit_credential(
            tenant_id="tenant-a", credential_id="cred-1",
            account_id="acct-1", fingerprint="a" * 64,
        )
        source.principal = _principal("owner-1")
        facade.decide_credential(
            tenant_id="tenant-a", credential_id="cred-1", approve=True
        )
        assert facade.credential_is_approved(
            tenant_id="tenant-a", credential_id="cred-1"
        )
        assert facade.production_ready is False
        assert repository.credential("tenant-a", "cred-1").status == "APPROVED"
    finally:
        repository.close()


def test_authenticated_owner_cannot_select_an_unassigned_tenant(tmp_path):
    facade, _source, _sessions, repository = _build(
        tmp_path, _principal("owner-1", tenants=("tenant-a",))
    )
    try:
        with pytest.raises(OwnerAuthorizationError):
            facade.invite_member(
                tenant_id="tenant-b", subject_id="member-2"
            )
        assert repository.membership("tenant-b", "member-2") is None
    finally:
        repository.close()


def test_expired_principal_and_revoked_session_fail_closed(tmp_path):
    facade, source, sessions, repository = _build(
        tmp_path, _principal("owner-1", expires=99.0)
    )
    try:
        with pytest.raises(OwnerAuthorizationError):
            facade.invite_member(
                tenant_id="tenant-a", subject_id="expired-member"
            )
        source.principal = _principal("owner-1", expires=200.0)
        sessions.active = False
        with pytest.raises(OwnerAuthorizationError):
            facade.invite_member(
                tenant_id="tenant-a", subject_id="revoked-member"
            )
        source.principal = None
        sessions.active = True
        with pytest.raises(OwnerAuthorizationError):
            facade.invite_member(
                tenant_id="tenant-a", subject_id="missing-principal"
            )
        assert repository.audit_events("tenant-a") == []
    finally:
        repository.close()


def test_postgres_adapters_do_not_claim_guc_based_tenant_isolation():
    delta = PostgreSQLDeltaAccountRepository(
        "postgresql://placeholder.invalid/quantengine"
    )
    governance = PostgreSQLOwnerGovernanceRepository(
        "postgresql://placeholder.invalid/quantengine"
    )
    assert delta.tenant_isolation_enforced is False
    assert governance.tenant_isolation_enforced is False
    assert delta.production_ready is False
    assert governance.production_ready is False
