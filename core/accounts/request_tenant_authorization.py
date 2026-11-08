"""Request-scoped tenant authorization primitives.

This is an adapter contract, not an authentication implementation. Only trusted
authentication middleware may bind a principal. Never construct or bind one
from request-body, query-string, or client-controlled data.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
import math
import time
from typing import Callable, FrozenSet, Iterator, Protocol

from core.accounts.delta_account_registry import AccountScopeError


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity and tenant membership established by trusted server middleware."""

    subject_id: str
    session_id: str
    tenant_ids: FrozenSet[str]
    expires_at_epoch: float


class TrustedPrincipalSource(Protocol):
    production_ready: bool

    def current_principal(self) -> AuthenticatedPrincipal | None:
        ...


class SessionStatusValidator(Protocol):
    production_ready: bool

    def is_session_active(self, principal: AuthenticatedPrincipal) -> bool:
        ...


_current_principal: ContextVar[AuthenticatedPrincipal | None] = ContextVar(
    "quantengine_authenticated_principal", default=None
)

_authorizer_principal_override: ContextVar[tuple[object, AuthenticatedPrincipal] | None] = ContextVar(
    "quantengine_authorizer_principal_override", default=None
)


@contextmanager
def bind_authenticated_principal(
    principal: AuthenticatedPrincipal,
) -> Iterator[None]:
    """Bind a verified principal for one request/task; trusted middleware only."""
    token: Token[AuthenticatedPrincipal | None] = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)


class ContextVarPrincipalSource:
    """Reads request context; deliberately not production-ready by itself."""

    production_ready = False

    def current_principal(self) -> AuthenticatedPrincipal | None:
        return _current_principal.get()


class RequestScopedTenantAuthorizer:
    """Fail-closed adapter for DeltaAccountRegistry tenant authorization."""

    def __init__(
        self,
        principal_source: TrustedPrincipalSource,
        session_validator: SessionStatusValidator,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._principal_source = principal_source
        self._session_validator = session_validator
        self._clock = clock

    @property
    def production_ready(self) -> bool:
        return (
            getattr(self._principal_source, "production_ready", False) is True
            and getattr(self._session_validator, "production_ready", False) is True
        )

    @contextmanager
    def bind_verified_principal(self, principal: AuthenticatedPrincipal) -> Iterator[None]:
        """Temporarily authorize a trusted worker using its claimed durable envelope.

        This is an internal trust boundary: callers must obtain the principal
        from the trusted job store, never from request payloads.
        """
        token = _authorizer_principal_override.set((self, principal))
        try:
            yield
        finally:
            _authorizer_principal_override.reset(token)

    def authorize_principal(self, tenant_id: str, principal: AuthenticatedPrincipal) -> bool:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise AccountScopeError("tenant authorization could not be verified")
        try:
            if not isinstance(principal, AuthenticatedPrincipal):
                raise ValueError("principal missing")
            if (
                not isinstance(principal.subject_id, str)
                or not principal.subject_id.strip()
                or not isinstance(principal.session_id, str)
                or not principal.session_id.strip()
                or not isinstance(principal.tenant_ids, frozenset)
                or any(not isinstance(item, str) or not item.strip()
                       for item in principal.tenant_ids)
                or isinstance(principal.expires_at_epoch, bool)
                or not isinstance(principal.expires_at_epoch, (int, float))
                or not math.isfinite(principal.expires_at_epoch)
                or principal.expires_at_epoch <= self._clock()
            ):
                raise ValueError("principal malformed or expired")
            if tenant_id not in principal.tenant_ids:
                return False
            if self._session_validator.is_session_active(principal) is not True:
                return False
            return True
        except AccountScopeError:
            raise
        except Exception:
            raise AccountScopeError("tenant authorization could not be verified") from None

    def _current_principal(self) -> AuthenticatedPrincipal:
        override = _authorizer_principal_override.get()
        if override is not None and override[0] is self:
            principal = override[1]
            refresh = getattr(self._principal_source, "refresh_persisted_principal", None)
            if callable(refresh):
                try:
                    principal = refresh(principal)
                except Exception:
                    raise AccountScopeError("tenant authorization could not be verified") from None
        else:
            try:
                principal = self._principal_source.current_principal()
            except Exception:
                raise AccountScopeError("tenant authorization could not be verified") from None
        if not isinstance(principal, AuthenticatedPrincipal):
            raise AccountScopeError("tenant authorization could not be verified")
        return principal

    def authorize_tenant(self, tenant_id: str) -> bool:
        return self.authorize_principal(tenant_id, self._current_principal())

    def current_subject_id(self, tenant_id: str) -> str:
        """Return the verified request subject for an authorized tenant."""
        principal = self._current_principal()
        if self.authorize_principal(tenant_id, principal) is not True:
            raise AccountScopeError("tenant is not authorized for this operation")
        return principal.subject_id
