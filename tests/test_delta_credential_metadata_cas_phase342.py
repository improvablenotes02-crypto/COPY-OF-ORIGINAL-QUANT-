"""Phase 342: credential rotation cannot overwrite concurrent account metadata."""

import hashlib

import pytest

from core.accounts.delta_account_registry import (
    AccountScopeError,
    CiphertextEnvelope,
    CredentialRotationConflictError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _IdentityExchange:
    def __init__(self, **kwargs):
        pass

    def _get_authenticated_account_id(self):
        return "987654"

    def close(self):
        pass


class _TestOnlyProvider:
    def __init__(self):
        self.on_encrypt = None

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        if self.on_encrypt is not None:
            callback, self.on_encrypt = self.on_encrypt, None
            callback()
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase342-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


def test_rotation_refuses_to_overwrite_identity_bound_after_its_initial_read(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "metadata-cas.sqlite3")
    provider = _TestOnlyProvider()
    registry = DeltaAccountRegistry(repository, provider, exchange_factory=_IdentityExchange)
    metadata = registry.register_account(
        tenant_id="tenant-phase342", label="metadata-cas", region="INDIA",
        environment="SANDBOX", api_key="original-key", api_secret="original-secret",
    )
    before = repository.get("tenant-phase342", metadata.account_id)

    def bind_identity_concurrently():
        repository.bind_provider_identity(
            "tenant-phase342", metadata.account_id, "987654"
        )

    provider.on_encrypt = bind_identity_concurrently
    try:
        with pytest.raises(CredentialRotationConflictError, match="changed concurrently"):
            registry.rotate_credentials(
                tenant_id="tenant-phase342", account_id=metadata.account_id,
                api_key="replacement-key", api_secret="replacement-secret",
            )
        after = repository.get("tenant-phase342", metadata.account_id)
        assert after.provider_account_id == "987654"
        assert after.credential_generation == before.credential_generation
        assert after.ciphertext == before.ciphertext
        assert after.key_id == before.key_id
        assert after.updated_at_ns > before.updated_at_ns
    finally:
        repository.close()
