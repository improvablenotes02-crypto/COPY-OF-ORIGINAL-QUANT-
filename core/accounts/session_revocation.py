"""Revocation-aware session validation contracts.

The persistent store is injected by deployment composition. This module
provides fail-closed enforcement and orchestration, not a fake durable store.
"""
from __future__ import annotations

from typing import Protocol

from core.accounts.request_tenant_authorization import AuthenticatedPrincipal


class SessionRevocationStore(Protocol):
    """Durable, strongly consistent session-revocation index."""

    production_ready: bool

    def is_revoked(self, subject_id: str, session_id: str) -> bool:
        ...

    def revoke(self, subject_id: str, session_id: str, *, revoked_at_epoch: float) -> None:
        ...


class RevocationAwareSessionStatusValidator:
    """Require both upstream identity-provider activity and local non-revocation."""

    def __init__(self, upstream_validator, revocation_store):
        if not callable(getattr(upstream_validator, "is_session_active", None)):
            raise ValueError("upstream session validator is required")
        if not callable(getattr(revocation_store, "is_revoked", None)):
            raise ValueError("session revocation store is required")
        self._upstream = upstream_validator
        self._store = revocation_store

    @property
    def production_ready(self) -> bool:
        return (
            getattr(self._upstream, "production_ready", False) is True
            and getattr(self._store, "production_ready", False) is True
            and callable(getattr(self._store, "revoke", None))
        )

    def is_session_active(self, principal: AuthenticatedPrincipal) -> bool:
        if not isinstance(principal, AuthenticatedPrincipal):
            return False
        if (
            not isinstance(principal.subject_id, str)
            or not principal.subject_id.strip()
            or not isinstance(principal.session_id, str)
            or not principal.session_id.strip()
        ):
            return False
        try:
            if self._upstream.is_session_active(principal) is not True:
                return False
            # Any store error is an authorization failure, never an allow.
            return self._store.is_revoked(
                principal.subject_id, principal.session_id
            ) is False
        except Exception:
            return False


class SessionRevocationCoordinator:
    """Revoke one verified identity-provider session in the local deny index."""

    def __init__(self, revocation_store, *, clock):
        if not callable(getattr(revocation_store, "revoke", None)):
            raise ValueError("session revocation store is required")
        if not callable(clock):
            raise ValueError("revocation clock is required")
        self._store = revocation_store
        self._clock = clock

    @property
    def production_ready(self) -> bool:
        return getattr(self._store, "production_ready", False) is True

    def revoke(self, principal: AuthenticatedPrincipal) -> None:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise PermissionError("verified session principal required")
        subject_id, session_id = principal.subject_id, principal.session_id
        if (
            not isinstance(subject_id, str) or not subject_id.strip()
            or not isinstance(session_id, str) or not session_id.strip()
        ):
            raise ValueError("verified session identity is malformed")
        timestamp = self._clock()
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise ValueError("revocation timestamp is invalid")
        self._store.revoke(subject_id, session_id, revoked_at_epoch=float(timestamp))
