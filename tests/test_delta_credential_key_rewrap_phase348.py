"""Phase 348: stored Delta credentials can be rewrapped under a new encryption key."""

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
        self.active_key_id = "kms-key-version-1"

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(
            associated_data + self.active_key_id.encode("utf-8")
        ).digest()[:16]
        return CiphertextEnvelope(self.active_key_id, "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(
            associated_data + envelope.key_id.encode("utf-8")
        ).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class _FakeExchange:
    def __init__(self, **kwargs):
        self.api_key = kwargs["api_key"]
        self.api_secret = kwargs["api_secret"]

    def close(self):
        pass


def test_rewrap_changes_encryption_key_without_changing_delta_credentials(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "key-rewrap.sqlite3")
    provider = _RotatingProvider()
    registry = DeltaAccountRegistry(
        repository, provider, exchange_factory=_FakeExchange
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase348", label="rewrap", region="INDIA",
        environment="SANDBOX", api_key="unchanged-api-key",
        api_secret="unchanged-api-secret",
    )
    before = repository.get("tenant-phase348", metadata.account_id)
    provider.active_key_id = "kms-key-version-2"
    try:
        rewrapped = registry.rewrap_credentials(
            tenant_id="tenant-phase348", account_id=metadata.account_id
        )
        after = repository.get("tenant-phase348", metadata.account_id)
        assert after.key_id == "kms-key-version-2"
        assert after.credential_generation == before.credential_generation + 1
        assert after.provider_account_id == before.provider_account_id
        assert after.ciphertext != before.ciphertext
        assert rewrapped.updated_at_ns == after.updated_at_ns

        session = registry.open_read_only_session(
            tenant_id="tenant-phase348", account_id=metadata.account_id
        )
        try:
            assert session._exchange.api_key == "unchanged-api-key"
            assert session._exchange.api_secret == "unchanged-api-secret"
        finally:
            session.close()

        events = repository.list_credential_rotation_events(
            "tenant-phase348", metadata.account_id
        )
        assert len(events) == 1
        assert events[0].previous_key_id == "kms-key-version-1"
        assert events[0].new_key_id == "kms-key-version-2"
    finally:
        repository.close()


def test_rewrap_rejects_provider_that_does_not_change_key_id(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "same-key-rewrap.sqlite3")
    provider = _RotatingProvider()
    registry = DeltaAccountRegistry(repository, provider)
    metadata = registry.register_account(
        tenant_id="tenant-phase348-same", label="same-key", region="INDIA",
        environment="SANDBOX", api_key="api-key", api_secret="api-secret",
    )
    before = repository.get("tenant-phase348-same", metadata.account_id)
    try:
        with pytest.raises(CredentialVaultError, match="did not select a new encryption key"):
            registry.rewrap_credentials(
                tenant_id="tenant-phase348-same", account_id=metadata.account_id
            )
        assert repository.get("tenant-phase348-same", metadata.account_id) == before
    finally:
        repository.close()
