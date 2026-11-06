"""Phase 350: encryption-key rewrap invalidates clients holding old credentials."""

import hashlib

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _RotatingProvider:
    def __init__(self):
        self.active_key_id = "key-v1"

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope(self.active_key_id, "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class _FakeExchange:
    def __init__(self, **kwargs):
        self.api_key = kwargs["api_key"]
        self.api_secret = kwargs["api_secret"]
        self.balance_calls = 0

    def get_balance(self):
        self.balance_calls += 1
        return {"success": True}

    def close(self):
        pass


def test_rewrap_revokes_existing_session_and_new_session_uses_same_api_credentials(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "rewrap-revocation.sqlite3")
    provider = _RotatingProvider()
    clients = []

    def factory(**kwargs):
        client = _FakeExchange(**kwargs)
        clients.append(client)
        return client

    registry = DeltaAccountRegistry(repository, provider, exchange_factory=factory)
    metadata = registry.register_account(
        tenant_id="tenant-phase350", label="rewrap-revocation", region="INDIA",
        environment="SANDBOX", api_key="same-api-key", api_secret="same-api-secret",
    )
    old_session = registry.open_read_only_session(
        tenant_id="tenant-phase350", account_id=metadata.account_id
    )
    provider.active_key_id = "key-v2"
    try:
        registry.rewrap_credentials(
            tenant_id="tenant-phase350", account_id=metadata.account_id
        )
        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            old_session.get_balance()
        assert clients[0].balance_calls == 0

        new_session = registry.open_read_only_session(
            tenant_id="tenant-phase350", account_id=metadata.account_id
        )
        try:
            assert clients[-1].api_key == "same-api-key"
            assert clients[-1].api_secret == "same-api-secret"
            assert new_session.get_balance() == {"success": True}
            assert clients[-1].balance_calls == 1
        finally:
            new_session.close()
    finally:
        old_session.close()
        repository.close()
