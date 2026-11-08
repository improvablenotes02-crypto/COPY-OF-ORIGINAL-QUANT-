"""Phases 379-381: integrated owner governance and credential admission."""
import pytest
from core.accounts.delta_account_registry import AccountScopeError
from core.accounts.oidc_tenant_principal import AuthenticatedPrincipal
from core.accounts.owner_governance import OwnerAuthorizationError, SQLiteOwnerGovernanceRepository
from core.accounts.request_tenant_authorization import ContextVarPrincipalSource, bind_authenticated_principal
import core.accounts.tenant_governance_runtime as runtime_module

class Sessions:
    production_ready = True
    def __init__(self): self.active = True
    def is_session_active(self, principal): return self.active

def principal(subject="owner-1", tenants=frozenset({"tenant-a"})):
    return AuthenticatedPrincipal(subject, "session-1", tenants, 9999999999)

@pytest.fixture
def runtime(monkeypatch):
    repositories = []
    class TestPostgresRepository(SQLiteOwnerGovernanceRepository):
        production_ready = False
        durable_shared_storage = True
        tenant_isolation_enforced = True
        def __init__(self, resolver, *, connect_timeout=5):
            super().__init__()
            repositories.append(self)
    monkeypatch.setattr(runtime_module, "AuthenticatedPostgreSQLOwnerGovernanceRepository", TestPostgresRepository)
    source, sessions = ContextVarPrincipalSource(), Sessions()
    service = runtime_module.AuthenticatedTenantGovernanceRuntime(
        owner_subject_id="owner-1", principal_source=source,
        session_validator=sessions,
        tenant_dsn_resolver=lambda tenant: "test-only-" + tenant,
    )
    yield service, source, sessions, repositories
    for repository in repositories: repository.close()

def test_runtime_builds_owner_api_with_encrypted_registry_and_shared_tenant_guard(runtime, monkeypatch):
    service, _source, _sessions, _repositories = runtime
    captured = {}
    class FakeDeltaPersistence: pass
    class FakeRegistry:
        production_ready = False
        def __init__(self, repository, encryption_provider, *, tenant_authorizer,
                     credential_approval_provider, require_production_security):
            captured.update(repository=repository, encryption_provider=encryption_provider,
                            tenant_authorizer=tenant_authorizer,
                            credential_approval_provider=credential_approval_provider,
                            require_production_security=require_production_security)
    sentinel_server = object()
    def fake_persistence(resolver, *, connect_timeout):
        captured.update(resolver=resolver, timeout=connect_timeout)
        return FakeDeltaPersistence()
    def fake_repository(repository, authorizer):
        captured.update(persistence=repository, repository_authorizer=authorizer)
        return object()
    def fake_server(governance, **kwargs):
        captured.update(governance=governance, server_kwargs=kwargs)
        return sentinel_server
    monkeypatch.setattr(runtime_module, "AuthenticatedPostgreSQLDeltaAccountRepository", fake_persistence)
    monkeypatch.setattr(runtime_module, "TenantDeltaAccountRepository", fake_repository)
    monkeypatch.setattr(runtime_module, "DeltaAccountRegistry", FakeRegistry)
    monkeypatch.setattr(runtime_module, "create_owner_governance_server", fake_server)
    encryption_provider = object()
    assert service.create_owner_governance_server(
        encryption_provider=encryption_provider, allow_nonproduction=True
    ) is sentinel_server
    assert captured["encryption_provider"] is encryption_provider
    assert captured["resolver"] is not None
    assert captured["timeout"] == 5
    assert captured["tenant_authorizer"] is service.tenant_authorizer
    assert captured["repository_authorizer"] is service.tenant_authorizer
    assert captured["credential_approval_provider"] is service.credential_approval_provider
    assert captured["require_production_security"] is False
    assert captured["governance"] is service.owner_governance
    assert captured["server_kwargs"]["account_registry"] is service.delta_account_registry
    assert captured["server_kwargs"]["allow_nonproduction"] is True

def test_runtime_refuses_unapproved_encryption_provider_in_production_mode(runtime):
    from core.accounts.owner_governance_api import ProductionAdmissionError
    service, *_ = runtime
    with pytest.raises(ProductionAdmissionError, match="approved credential encryption provider"):
        service.create_owner_governance_server(
            encryption_provider=object(), allow_nonproduction=False
        )


def test_phase379_composes_owner_only_governance_over_tenant_guard(runtime):
    service, _source, _sessions, repositories = runtime
    with bind_authenticated_principal(principal()):
        service.owner_governance.invite_member(tenant_id="tenant-a", subject_id="member-1", permissions=("read",))
        service.owner_governance.decide_member(tenant_id="tenant-a", subject_id="member-1", approve=True, permissions=("read",))
    with bind_authenticated_principal(principal("member-1")):
        with pytest.raises(OwnerAuthorizationError, match="owner authorization required"):
            service.owner_governance.decide_member(tenant_id="tenant-a", subject_id="member-1", approve=False)
    assert repositories[0].membership("tenant-a", "member-1").status == "APPROVED"
    assert service.production_ready is False

def test_phase379_rejects_cross_tenant_before_governance_storage(runtime):
    service, _source, _sessions, repositories = runtime
    with bind_authenticated_principal(principal()):
        with pytest.raises(OwnerAuthorizationError, match="authenticated tenant principal required"):
            service.owner_governance.invite_member(tenant_id="tenant-b", subject_id="member-2")
    assert repositories[0].membership("tenant-b", "member-2") is None

def test_phase380_owner_invites_member_and_approves_members_credential(runtime):
    service, _source, _sessions, _repositories = runtime
    fingerprint = "a" * 64
    with bind_authenticated_principal(principal()):
        service.owner_governance.invite_member(
            tenant_id="tenant-a", subject_id="member-1", permissions=("read",)
        )
        service.owner_governance.decide_member(
            tenant_id="tenant-a", subject_id="member-1",
            approve=True, permissions=("read",),
        )
    with bind_authenticated_principal(principal("member-1")):
        service.owner_governance.submit_credential(
            tenant_id="tenant-a", credential_id="cred-1",
            account_id="acct-1", fingerprint=fingerprint,
        )
        with pytest.raises(OwnerAuthorizationError, match="owner authorization required"):
            service.owner_governance.decide_credential(
                tenant_id="tenant-a", credential_id="cred-1", approve=True
            )
        assert not service.credential_approval_provider.is_approved(
            tenant_id="tenant-a", account_id="acct-1", fingerprint=fingerprint
        )
    with bind_authenticated_principal(principal()):
        service.owner_governance.decide_credential(
            tenant_id="tenant-a", credential_id="cred-1", approve=True
        )
        assert service.credential_approval_provider.is_approved(
            tenant_id="tenant-a", account_id="acct-1", fingerprint=fingerprint
        )

def test_phase380_credential_lookup_without_trusted_context_fails_closed(runtime):
    service, _source, _sessions, _repositories = runtime
    with pytest.raises(AccountScopeError):
        service.credential_approval_provider.is_approved(tenant_id="tenant-a", account_id="acct-1", fingerprint="a" * 64)

def test_phase381_revocation_is_observed_by_existing_approval_provider(runtime):
    service, _source, _sessions, _repositories = runtime
    fingerprint = "b" * 64
    with bind_authenticated_principal(principal()):
        service.owner_governance.submit_credential(tenant_id="tenant-a", credential_id="cred-2", account_id="acct-2", fingerprint=fingerprint)
        service.owner_governance.decide_credential(tenant_id="tenant-a", credential_id="cred-2", approve=True)
        provider = service.credential_approval_provider
        assert provider.is_approved(tenant_id="tenant-a", account_id="acct-2", fingerprint=fingerprint)
        service.owner_governance.revoke_credential(tenant_id="tenant-a", credential_id="cred-2")
        assert not provider.is_approved(tenant_id="tenant-a", account_id="acct-2", fingerprint=fingerprint)

def test_phase381_session_revocation_blocks_governance_and_credential_reads(runtime):
    service, _source, sessions, _repositories = runtime
    sessions.active = False
    with bind_authenticated_principal(principal()):
        with pytest.raises(OwnerAuthorizationError, match="authenticated tenant principal required"):
            service.owner_governance.invite_member(tenant_id="tenant-a", subject_id="blocked")
        with pytest.raises(AccountScopeError):
            service.credential_approval_provider.is_approved(tenant_id="tenant-a", account_id="acct-a", fingerprint="c" * 64)
