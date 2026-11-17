"""Phase 335: persisted account changes revoke already-open read sessions."""

import hashlib

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase335-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class FakeExchange:
    def __init__(self, **kwargs):
        self.balance_calls = 0
        self.close_calls = 0

    def get_balance(self):
        self.balance_calls += 1
        return {"success": True}

    def close(self):
        self.close_calls += 1


def make_registry():
    repository = SQLiteDeltaAccountRepository()
    clients = []

    def factory(**kwargs):
        client = FakeExchange(**kwargs)
        clients.append(client)
        return client

    registry = DeltaAccountRegistry(
        repository, TestOnlyProvider(), exchange_factory=factory
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase335",
        label="revocation-test",
        region="INDIA",
        environment="SANDBOX",
        api_key="not-a-real-key",
        api_secret="not-a-real-secret",
    )
    session = registry.open_read_only_session(
        tenant_id="tenant-phase335", account_id=metadata.account_id
    )
    return repository, registry, metadata, session, clients[0]


def test_deleting_account_revokes_existing_session_before_next_exchange_call():
    repository, registry, metadata, session, client = make_registry()
    try:
        assert registry.delete_account(
            tenant_id="tenant-phase335", account_id=metadata.account_id
        ) is True
        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_balance()
        assert client.balance_calls == 0
    finally:
        session.close()
        repository.close()


def test_provider_identity_binding_invalidates_pre_binding_session():
    repository, registry, metadata, session, client = make_registry()
    try:
        current = repository.get("tenant-phase335", metadata.account_id)
        assert current is not None
        repository.bind_provider_identity(
            "tenant-phase335",
            metadata.account_id,
            "123456",
            expected_generation=current.credential_generation,
            expected_updated_at_ns=current.updated_at_ns,
            authorization_check=lambda: True,
        )
        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_balance()
        assert client.balance_calls == 0
    finally:
        session.close()
        repository.close()


def test_repository_authorization_failure_is_sanitized_and_fails_closed():
    repository, registry, metadata, session, client = make_registry()
    try:
        repository.close()
        with pytest.raises(
            CredentialVaultError, match="authorization could not be verified"
        ):
            session.get_balance()
        assert client.balance_calls == 0
    finally:
        session.close()
