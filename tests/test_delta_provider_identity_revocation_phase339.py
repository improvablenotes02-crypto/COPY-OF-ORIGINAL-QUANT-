"""Phase 339: provider identity changes revoke sessions across repository connections."""

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
        return CiphertextEnvelope("phase339-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class FakeExchange:
    def __init__(self, **kwargs):
        self.balance_calls = 0

    def get_balance(self):
        self.balance_calls += 1
        return {"success": True}

    def close(self):
        pass


def test_provider_identity_binding_from_another_connection_revokes_existing_session(tmp_path):
    database = tmp_path / "shared-accounts.sqlite3"
    session_repository = SQLiteDeltaAccountRepository(database)
    binding_repository = SQLiteDeltaAccountRepository(database)
    clients = []

    def factory(**kwargs):
        client = FakeExchange(**kwargs)
        clients.append(client)
        return client

    registry = DeltaAccountRegistry(
        session_repository, TestOnlyProvider(), exchange_factory=factory
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase339",
        label="cross-connection-identity-binding",
        region="INDIA",
        environment="SANDBOX",
        api_key="not-a-real-key",
        api_secret="not-a-real-secret",
    )
    session = registry.open_read_only_session(
        tenant_id="tenant-phase339", account_id=metadata.account_id
    )

    try:
        assert session.get_balance() == {"success": True}
        assert clients[0].balance_calls == 1

        current = binding_repository.get("tenant-phase339", metadata.account_id)
        binding_repository.bind_provider_identity(
            "tenant-phase339",
            metadata.account_id,
            "987654",
            expected_generation=current.credential_generation,
            expected_updated_at_ns=current.updated_at_ns,
            authorization_check=lambda: True,
        )

        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_balance()
        assert clients[0].balance_calls == 1
    finally:
        session.close()
        binding_repository.close()
        session_repository.close()
