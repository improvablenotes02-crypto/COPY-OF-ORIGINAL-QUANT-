"""Phases 376-378: trusted repository factory, governance guard, task identity."""
import pytest

from core.accounts.delta_account_registry import AccountScopeError
from core.accounts.oidc_tenant_principal import AuthenticatedPrincipal
from core.accounts.postgres_tenant_services import (
    AuthenticatedTenantRepositoryFactory,
    TenantBackgroundTaskRunner,
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
    governance = services.governance_repository()
    assert delta.tenant_isolation_enforced is True
    assert delta.production_ready is False
    assert governance.production_ready is False
    assert services.production_ready is False


def test_governance_facade_checks_membership_before_every_operation():
    services, _, _, _ = factory()
    repo = services.governance_repository()
    with bind_authenticated_principal(principal()):
        with pytest.raises(AccountScopeError, match="not authorized"):
            repo.membership("tenant-b", "member-b")
        assert repo.membership("tenant-a", "member-a") is None
        with pytest.raises(AccountScopeError):
            repo.audit_events("tenant-b")


def test_governance_facade_does_not_confuse_membership_with_owner_role():
    services, _, _, _ = factory()
    repo = services.governance_repository()
    with bind_authenticated_principal(principal()):
        # The tenant guard allows this request to reach domain persistence;
        # owner-only approval remains the governance service's responsibility.
        assert callable(repo.decide_credential)


def test_background_task_revalidates_tenant_and_session():
    services, _, sessions, _ = factory()
    runner = TenantBackgroundTaskRunner(services.tenant_authorizer)
    with bind_authenticated_principal(principal()):
        assert runner.run(principal(), "tenant-a", lambda x: x + 1, 4) == 5
        with pytest.raises(AccountScopeError):
            runner.run(principal(), "tenant-b", lambda: "must not run")
        sessions.active = False
        with pytest.raises(AccountScopeError):
            runner.run(principal(), "tenant-a", lambda: "must not run")


def test_background_task_context_is_restored_after_callback_failure():
    services, _, _, _ = factory()
    runner = TenantBackgroundTaskRunner(services.tenant_authorizer)
    with pytest.raises(RuntimeError, match="task failed"):
        runner.run(principal(), "tenant-a", lambda: (_ for _ in ()).throw(RuntimeError("task failed")))
    with pytest.raises(AccountScopeError, match="could not be verified"):
        services.tenant_authorizer.authorize_tenant("tenant-a")


def test_background_task_rejects_untrusted_principal_and_callback():
    services, _, _, _ = factory()
    runner = TenantBackgroundTaskRunner(services.tenant_authorizer)
    with pytest.raises(AccountScopeError):
        runner.run(object(), "tenant-a", lambda: None)
    with pytest.raises(ValueError):
        runner.run(principal(), "tenant-a", None)


def test_repository_factory_rejects_untrusted_resolver():
    with pytest.raises(ValueError, match="server-configured"):
        AuthenticatedTenantRepositoryFactory(
            principal_source=ContextVarPrincipalSource(),
            session_validator=SessionValidator(),
            tenant_dsn_resolver=None,
        )
