"""Phase 307: deleting an account invalidates already-open read-only sessions."""
import hashlib

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestEncryptionProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope(
            "test-only-key", "TEST-ONLY-XOR",
            tag + bytes(value ^ 0xA5 for value in plaintext),
        )

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])


class _TenantIdentity:
    production_ready = False

    def authorize_tenant(self, tenant_id: str) -> bool:
        return tenant_id == "tenant-owner"


class _ReadOnlyExchange:
    def __init__(self, **kwargs):
        self.balance_calls = 0
        self.closed = False

    def get_balance(self):
        self.balance_calls += 1
        return {"success": True, "result": []}

    def close(self):
        self.closed = True


def test_deleting_account_blocks_existing_read_only_session_before_exchange_call():
    repository = SQLiteDeltaAccountRepository()
    exchanges = []

    def exchange_factory(**kwargs):
        exchange = _ReadOnlyExchange(**kwargs)
        exchanges.append(exchange)
        return exchange

    registry = DeltaAccountRegistry(
        repository,
        _TestEncryptionProvider(),
        exchange_factory=exchange_factory,
        tenant_authorizer=_TenantIdentity(),
    )
    try:
        account = registry.register_account(
            tenant_id="tenant-owner",
            label="Owner Delta",
            region="INDIA",
            environment="SANDBOX",
            api_key="initial-key",
            api_secret="initial-secret",
        )
        session = registry.open_read_only_session(
            tenant_id="tenant-owner", account_id=account.account_id
        )
        assert len(exchanges) == 1
        assert session.closed is False

        assert registry.delete_account(
            tenant_id="tenant-owner", account_id=account.account_id
        ) is True

        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_balance()

        # Authorization is checked before touching the venue client.
        assert exchanges[0].balance_calls == 0
        session.close()
        assert session.closed is True
        assert exchanges[0].closed is True
    finally:
        repository.close()
