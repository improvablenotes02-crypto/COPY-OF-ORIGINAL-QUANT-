"""Phase 338: account deletion through another repository connection revokes sessions."""

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
        return CiphertextEnvelope("phase338-test-key", "TEST-ONLY", tag + plaintext)

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


def test_delete_from_independent_repository_connection_revokes_open_session(tmp_path):
    database = tmp_path / "shared-accounts.sqlite3"
    session_repository = SQLiteDeltaAccountRepository(database)
    deletion_repository = SQLiteDeltaAccountRepository(database)
    clients = []

    def factory(**kwargs):
        client = FakeExchange(**kwargs)
        clients.append(client)
        return client

    registry = DeltaAccountRegistry(
        session_repository, TestOnlyProvider(), exchange_factory=factory
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase338",
        label="cross-connection-revocation",
        region="INDIA",
        environment="SANDBOX",
        api_key="not-a-real-key",
        api_secret="not-a-real-secret",
    )
    session = registry.open_read_only_session(
        tenant_id="tenant-phase338", account_id=metadata.account_id
    )

    try:
        assert session.get_balance() == {"success": True}
        assert clients[0].balance_calls == 1

        # A second repository connection observes and deletes the same record.
        assert deletion_repository.get(
            "tenant-phase338", metadata.account_id
        ) is not None
        assert deletion_repository.delete(
            "tenant-phase338", metadata.account_id
        ) is True

        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_balance()
        assert clients[0].balance_calls == 1
    finally:
        session.close()
        deletion_repository.close()
        session_repository.close()
