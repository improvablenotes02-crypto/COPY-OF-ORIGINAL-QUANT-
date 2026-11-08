"""Phases 376-378: trusted repository factory, governance guard, task identity."""
import pytest

from core.accounts.delta_account_registry import AccountScopeError
from core.accounts.oidc_tenant_principal import AuthenticatedPrincipal
from core.accounts.postgres_tenant_services import (
    AuthenticatedTenantRepositoryFactory,
    TenantBackgroundTaskRunner, SQLiteBackgroundJobStore,
)
from core.accounts.request_tenant_authorization import (
    ContextVarPrincipalSource, RequestScopedTenantAuthorizer,
    bind_authenticated_principal,
)


class SessionValidator:
    production_ready = True
    def __init__(self, active=True): self.active = active
    def is_session_active(self, principal): return self.active


def principal(tenants=frozenset({"tenant-a"}), expires=9999999999):
    return AuthenticatedPrincipal("subject-1", "session-1", tenants, expires)


class _FakeGovernance:
    def membership(self, tenant, subject): return None
    def audit_events(self, tenant): return []


class _FakeDelta:
    def __init__(self): self.calls = []
    def get(self, tenant, account): self.calls.append((tenant, account)); return None


def factory():
    source = ContextVarPrincipalSource()
    sessions = SessionValidator()
    calls = []
    def resolver(tenant):
        calls.append(tenant)
        return "dsn-for-" + tenant
    services = AuthenticatedTenantRepositoryFactory(
        principal_source=source, session_validator=sessions,
        tenant_dsn_resolver=resolver,
    )
    return services, source, sessions, calls


def test_factory_only_builds_authenticated_postgres_repositories():
    services, _, _, _ = factory()
    delta = services.delta_repository()
    services._governance_persistence = lambda: _FakeGovernance()
    governance = services.governance_repository()
    assert delta.tenant_isolation_enforced is True
    assert delta.production_ready is False
    assert governance.production_ready is False
    assert services.production_ready is False


def test_governance_facade_checks_membership_before_every_operation():
    services, _, _, _ = factory()
    services._governance_persistence = lambda: _FakeGovernance()
    repo = services.governance_repository()
    with bind_authenticated_principal(principal()):
        with pytest.raises(AccountScopeError, match="not authorized"):
            repo.membership("tenant-b", "member-b")
        assert repo.membership("tenant-a", "member-a") is None
        with pytest.raises(AccountScopeError):
            repo.audit_events("tenant-b")


def test_governance_facade_does_not_confuse_membership_with_owner_role():
    services, _, _, _ = factory()
    services._governance_persistence = lambda: _FakeGovernance()
    repo = services.governance_repository()
    with bind_authenticated_principal(principal()):
        # The tenant guard allows this request to reach domain persistence;
        # owner-only approval remains the governance service's responsibility.
        assert callable(repo.decide_credential)


def test_background_task_revalidates_tenant_and_session(tmp_path):
    services, _, sessions, _ = factory()
    store = SQLiteBackgroundJobStore(str(tmp_path / "jobs.sqlite3"), clock=lambda: 100.0)
    runner = TenantBackgroundTaskRunner(store, services.tenant_authorizer)
    job = store.enqueue(principal(), "tenant-a")
    assert runner.run(job, lambda x: x + 1, 4) == 5

    scoped_job = store.enqueue(principal(), "tenant-a")
    assert runner.run(
        scoped_job, lambda: services.tenant_authorizer.authorize_tenant("tenant-b")
    ) is False

    revoked_job = store.enqueue(principal(), "tenant-a")
    sessions.active = False
    with pytest.raises(AccountScopeError):
        runner.run(revoked_job, lambda: "must not run")


def test_background_task_uses_persisted_principal_with_oidc_request_source(tmp_path):
    class EmptyOidcSource:
        production_ready = True
        def current_principal(self): return None

    sessions = SessionValidator()
    authorizer = RequestScopedTenantAuthorizer(EmptyOidcSource(), sessions)
    store = SQLiteBackgroundJobStore(str(tmp_path / "oidc-worker.sqlite3"), clock=lambda: 100.0)
    runner = TenantBackgroundTaskRunner(store, authorizer)
    job = store.enqueue(principal(), "tenant-a")
    assert runner.run(job, lambda: authorizer.authorize_tenant("tenant-a")) is True
    with pytest.raises(AccountScopeError):
        authorizer.authorize_tenant("tenant-a")


def test_background_task_context_is_restored_after_callback_failure(tmp_path):
    services, _, _, _ = factory()
    store = SQLiteBackgroundJobStore(str(tmp_path / "jobs.sqlite3"), clock=lambda: 100.0)
    runner = TenantBackgroundTaskRunner(store, services.tenant_authorizer)
    job = store.enqueue(principal(), "tenant-a")
    with pytest.raises(RuntimeError, match="task failed"):
        runner.run(job, lambda: (_ for _ in ()).throw(RuntimeError("task failed")))
    with pytest.raises(AccountScopeError, match="could not be verified"):
        services.tenant_authorizer.authorize_tenant("tenant-a")


def test_background_task_rejects_untrusted_job_and_callback(tmp_path):
    services, _, _, _ = factory()
    store = SQLiteBackgroundJobStore(str(tmp_path / "jobs.sqlite3"), clock=lambda: 100.0)
    runner = TenantBackgroundTaskRunner(store, services.tenant_authorizer)
    job = store.enqueue(principal(), "tenant-a")
    with pytest.raises(AccountScopeError):
        runner.run("missing-job", lambda: None)
    with pytest.raises(ValueError):
        runner.run(job, None)
    with pytest.raises(AccountScopeError):
        runner.run(principal(), lambda: None)


def test_repository_factory_rejects_untrusted_resolver():
    with pytest.raises(ValueError, match="server-configured"):
        AuthenticatedTenantRepositoryFactory(
            principal_source=ContextVarPrincipalSource(),
            session_validator=SessionValidator(),
            tenant_dsn_resolver=None,
        )

def test_delta_repository_facade_checks_tenant_before_storage():
    services, _, _, _ = factory()
    fake = _FakeDelta()
    services._resolver = lambda tenant: "unused"
    from core.accounts.postgres_tenant_services import TenantDeltaAccountRepository
    guarded = TenantDeltaAccountRepository(fake, services.tenant_authorizer)
    with bind_authenticated_principal(principal()):
        assert guarded.get("tenant-a", "acct-a") is None
        with pytest.raises(AccountScopeError, match="not authorized"):
            guarded.get("tenant-b", "acct-b")
    assert fake.calls == [("tenant-a", "acct-a")]
