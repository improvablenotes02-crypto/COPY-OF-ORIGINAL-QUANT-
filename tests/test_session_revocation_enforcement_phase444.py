"""Phases 444-446: revocation-aware session enforcement."""
import pytest

from core.accounts.request_tenant_authorization import AuthenticatedPrincipal
from core.accounts.session_revocation import (
    RevocationAwareSessionStatusValidator,
    SessionRevocationCoordinator,
)


class MemoryRevocations:
    production_ready = False

    def __init__(self):
        self.revoked = set()
        self.fail_reads = False

    def is_revoked(self, subject, session):
        if self.fail_reads:
            raise RuntimeError("store unavailable")
        return (subject, session) in self.revoked

    def revoke(self, subject, session, *, revoked_at_epoch):
        self.revoked.add((subject, session))


class Upstream:
    production_ready = True

    def __init__(self):
        self.active = True

    def is_session_active(self, principal):
        return self.active


def principal(subject="member-1", session="session-1"):
    return AuthenticatedPrincipal(subject, session, frozenset({"tenant-a"}), 9999999999)


def test_revocation_coordinator_immediately_blocks_existing_principal():
    store, upstream = MemoryRevocations(), Upstream()
    validator = RevocationAwareSessionStatusValidator(upstream, store)
    coordinator = SessionRevocationCoordinator(store, clock=lambda: 123.5)
    current = principal()
    assert validator.is_session_active(current)
    coordinator.revoke(current)
    assert not validator.is_session_active(current)
    assert validator.is_session_active(principal(session="session-2"))


def test_upstream_revocation_and_local_revocation_are_both_enforced():
    store, upstream = MemoryRevocations(), Upstream()
    validator = RevocationAwareSessionStatusValidator(upstream, store)
    current = principal()
    store.revoke(current.subject_id, current.session_id, revoked_at_epoch=1)
    assert not validator.is_session_active(current)
    store.revoked.clear()
    upstream.active = False
    assert not validator.is_session_active(current)


def test_revocation_store_failure_fails_closed():
    store, upstream = MemoryRevocations(), Upstream()
    validator = RevocationAwareSessionStatusValidator(upstream, store)
    store.fail_reads = True
    assert not validator.is_session_active(principal())


def test_coordinator_rejects_unverified_or_malformed_identity():
    store = MemoryRevocations()
    coordinator = SessionRevocationCoordinator(store, clock=lambda: 1)
    with pytest.raises(PermissionError):
        coordinator.revoke(None)
    malformed = AuthenticatedPrincipal("", "session", frozenset(), 9999999999)
    with pytest.raises(ValueError):
        coordinator.revoke(malformed)


def test_production_readiness_requires_durable_store_and_upstream():
    store, upstream = MemoryRevocations(), Upstream()
    validator = RevocationAwareSessionStatusValidator(upstream, store)
    coordinator = SessionRevocationCoordinator(store, clock=lambda: 1)
    assert validator.production_ready is False
    assert coordinator.production_ready is False
    store.production_ready = True
    assert validator.production_ready is True
    assert coordinator.production_ready is True


def test_repeated_revocation_is_idempotent_for_store_contract():
    store = MemoryRevocations()
    coordinator = SessionRevocationCoordinator(store, clock=lambda: 7)
    current = principal()
    coordinator.revoke(current)
    coordinator.revoke(current)
    assert store.revoked == {(current.subject_id, current.session_id)}
