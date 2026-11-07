"""OIDC token-to-tenant principal adapter.

Cryptographic token verification and tenant membership are injected services.
This module never parses or trusts unverified JWT claims and never accepts
tenant membership from the token or request payload.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
import math
import time
from typing import Callable, FrozenSet, Iterator, Protocol

from core.accounts.request_tenant_authorization import AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class VerifiedAccessToken:
    """Claims returned only after issuer/signature/audience checks succeed."""
    subject_id: str
    session_id: str
    expires_at_epoch: float


class AccessTokenVerifier(Protocol):
    """OIDC/JWT adapter enforcing issuer, audience, signature and claim policy."""
    production_ready: bool

    def verify_access_token(self, token: str) -> VerifiedAccessToken:
        ...


class TenantMembershipResolver(Protocol):
    """Authoritative server-side membership lookup, never token-supplied data."""
    production_ready: bool

    def tenant_ids_for_subject(self, subject_id: str) -> FrozenSet[str]:
        ...


_access_token: ContextVar[str | None] = ContextVar(
    "quantengine_oidc_access_token", default=None
)


@contextmanager
def bind_access_token(token_value: str) -> Iterator[None]:
    """Bind an HTTP bearer token for one request; trusted middleware only."""
    if not isinstance(token_value, str) or not token_value.strip():
        raise ValueError("a non-empty bearer token is required")
    token: Token[str | None] = _access_token.set(token_value.strip())
    try:
        yield
    finally:
        _access_token.reset(token)


class OidcTenantPrincipalSource:
    """Build trusted principals from verified claims and database membership."""

    def __init__(
        self,
        token_verifier: AccessTokenVerifier,
        membership_resolver: TenantMembershipResolver,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token_verifier = token_verifier
        self._membership_resolver = membership_resolver
        self._clock = clock

    @property
    def production_ready(self) -> bool:
        return (
            getattr(self._token_verifier, "production_ready", False) is True
            and getattr(self._membership_resolver, "production_ready", False) is True
        )

    def current_principal(self) -> AuthenticatedPrincipal | None:
        token = _access_token.get()
        if token is None:
            return None
        try:
            claims = self._token_verifier.verify_access_token(token)
            if not isinstance(claims, VerifiedAccessToken):
                raise ValueError("verified claims missing")
            if (
                not isinstance(claims.subject_id, str)
                or not claims.subject_id.strip()
                or not isinstance(claims.session_id, str)
                or not claims.session_id.strip()
                or isinstance(claims.expires_at_epoch, bool)
                or not isinstance(claims.expires_at_epoch, (int, float))
                or not math.isfinite(claims.expires_at_epoch)
                or claims.expires_at_epoch <= self._clock()
            ):
                raise ValueError("verified claims malformed or expired")
            tenant_ids = self._membership_resolver.tenant_ids_for_subject(
                claims.subject_id
            )
            if (
                not isinstance(tenant_ids, frozenset)
                or any(not isinstance(item, str) or not item.strip()
                       for item in tenant_ids)
            ):
                raise ValueError("authoritative membership result malformed")
            return AuthenticatedPrincipal(
                subject_id=claims.subject_id,
                session_id=claims.session_id,
                tenant_ids=tenant_ids,
                expires_at_epoch=float(claims.expires_at_epoch),
            )
        except Exception:
            raise PermissionError("authenticated principal unavailable") from None
