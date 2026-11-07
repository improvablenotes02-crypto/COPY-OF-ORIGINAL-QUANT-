"""Phase 362: request-scoped principal and tenant authorization boundary."""
import asyncio
import pytest

from core.accounts.delta_account_registry import AccountScopeError
from core.accounts.request_tenant_authorization import (
    AuthenticatedPrincipal, ContextVarPrincipalSource,
    RequestScopedTenantAuthorizer, bind_authenticated_principal,
)


class _SessionValidator:
    production_ready = True
    def __init__(self, active=True):
        self.active = active
        self.error = False
    def is_session_active(self, principal):
        if self.error:
            raise RuntimeError("session-store private diagnostic")
        return self.active


class _TrustedSource(ContextVarPrincipalSource):
    production_ready = True


def _principal(tenants=frozenset({"tenant-a"}), expires=500.0):
    return AuthenticatedPrincipal("user-7", "session-9", tenants, expires)


def _authorizer(active=True, now=100.0):
    sessions = _SessionValidator(active)
    return RequestScopedTenantAuthorizer(
        _TrustedSource(), sessions, clock=lambda: now
    ), sessions


def test_request_context_authorizes_only_membership_and_active_session():
    authorizer, _ = _authorizer()
    with bind_authenticated_principal(_principal()):
        assert authorizer.authorize_tenant("tenant-a") is True
        assert authorizer.authorize_tenant("tenant-b") is False


def test_missing_principal_denies_without_throwing_identity_details():
    authorizer, _ = _authorizer()
    with pytest.raises(AccountScopeError, match="could not be verified"):
        authorizer.authorize_tenant("tenant-a")


@pytest.mark.parametrize("principal", [
    _principal(expires=100.0),
    AuthenticatedPrincipal("", "session-9", frozenset({"tenant-a"}), 500.0),
    AuthenticatedPrincipal("user-7", "session-9", {"tenant-a"}, 500.0),
    AuthenticatedPrincipal("user-7", "session-9", frozenset({"tenant-a"}), float("nan")),
])
def test_expired_or_malformed_principal_fails_closed(principal):
    authorizer, _ = _authorizer()
    with bind_authenticated_principal(principal):
        with pytest.raises(AccountScopeError, match="could not be verified"):
            authorizer.authorize_tenant("tenant-a")


def test_revoked_session_and_session_store_failure_deny():
    authorizer, sessions = _authorizer(active=False)
    with bind_authenticated_principal(_principal()):
        assert authorizer.authorize_tenant("tenant-a") is False
        sessions.active = True
        sessions.error = True
        with pytest.raises(AccountScopeError, match="could not be verified") as caught:
            authorizer.authorize_tenant("tenant-a")
        assert "private diagnostic" not in str(caught.value)


def test_production_readiness_requires_both_trusted_adapters():
    authorizer, sessions = _authorizer()
    assert authorizer.production_ready is True
    sessions.production_ready = False
    assert authorizer.production_ready is False


def test_context_is_restored_after_exception():
    authorizer, _ = _authorizer()
    with pytest.raises(RuntimeError):
        with bind_authenticated_principal(_principal()):
            assert authorizer.authorize_tenant("tenant-a") is True
            raise RuntimeError("request failed")
    with pytest.raises(AccountScopeError):
        authorizer.authorize_tenant("tenant-a")


def test_async_tasks_do_not_share_request_principals():
    authorizer, _ = _authorizer()
    async def check(tenant):
        with bind_authenticated_principal(_principal(frozenset({tenant}))):
            await asyncio.sleep(0)
            return (authorizer.authorize_tenant(tenant),
                    authorizer.authorize_tenant("other-tenant"))
    async def run():
        return await asyncio.gather(check("tenant-a"), check("tenant-b"))
    assert asyncio.run(run()) == [(True, False), (True, False)]
