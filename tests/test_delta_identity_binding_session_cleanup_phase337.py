"""Phase 337: identity verification always closes its temporary client session."""

import hashlib

import pytest

from core.accounts.delta_account_registry import (
    AccountScopeError,
    CiphertextEnvelope,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase337-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class IdentityExchange:
    def __init__(self, identity, **kwargs):
        self.identity = identity
        self.close_calls = 0

    def _get_authenticated_account_id(self):
        return self.identity

    def close(self):
        self.close_calls += 1


def make_registry(identity):
    repository = SQLiteDeltaAccountRepository()
    clients = []

    def factory(**kwargs):
        client = IdentityExchange(identity, **kwargs)
        clients.append(client)
        return client

    registry = DeltaAccountRegistry(
        repository, TestOnlyProvider(), exchange_factory=factory
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase337",
        label="identity-binding-cleanup",
        region="INDIA",
        environment="SANDBOX",
        api_key="not-a-real-key",
        api_secret="not-a-real-secret",
    )
    return repository, registry, metadata, clients


def test_invalid_provider_identity_still_closes_temporary_session():
    repository, registry, metadata, clients = make_registry("not-numeric")
    try:
        with pytest.raises(AccountScopeError, match="missing or invalid"):
            registry.verify_and_bind_identity(
                tenant_id="tenant-phase337", account_id=metadata.account_id
            )
        assert len(clients) == 1
        assert clients[0].close_calls == 1
        record = repository.get("tenant-phase337", metadata.account_id)
        assert record is not None
        assert record.provider_account_id is None
    finally:
        repository.close()


def test_successful_provider_identity_binding_closes_temporary_session():
    repository, registry, metadata, clients = make_registry("987654")
    try:
        bound = registry.verify_and_bind_identity(
            tenant_id="tenant-phase337", account_id=metadata.account_id
        )
        assert bound.provider_account_id == "987654"
        assert len(clients) == 1
        assert clients[0].close_calls == 1
    finally:
        repository.close()
