"""Phase 344: replacement Delta credentials must authenticate as the same account."""

import hashlib

import pytest

from core.accounts.delta_account_registry import (
    AccountScopeError,
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase344-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class _IdentityProbe:
    def __init__(self, identity, *, failure=None, **kwargs):
        self.identity = identity
        self.failure = failure
        self.close_calls = 0

    def _get_authenticated_account_id(self):
        if self.failure is not None:
            raise self.failure
        return self.identity

    def close(self):
        self.close_calls += 1


def test_valid_rotation_binds_verified_identity_for_previously_unbound_account(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "valid-identity.sqlite3")
    probes = []

    def factory(**kwargs):
        probe = _IdentityProbe("987654", **kwargs)
        probes.append(probe)
        return probe

    registry = DeltaAccountRegistry(repository, _TestOnlyProvider(), exchange_factory=factory)
    metadata = registry.register_account(
        tenant_id="tenant-phase344", label="valid", region="INDIA",
        environment="SANDBOX", api_key="old-key", api_secret="old-secret",
    )
    try:
        rotated = registry.rotate_credentials(
            tenant_id="tenant-phase344", account_id=metadata.account_id,
            api_key="new-key", api_secret="new-secret",
        )
        current = repository.get("tenant-phase344", metadata.account_id)
        assert current.provider_account_id == "987654"
        assert current.credential_generation == 2
        assert rotated.provider_account_id == "987654"
        assert probes[0].close_calls == 1
    finally:
        repository.close()


def test_rotation_rejects_credentials_for_a_different_bound_identity(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "wrong-identity.sqlite3")
    probes = []

    def factory(**kwargs):
        probe = _IdentityProbe("222222", **kwargs)
        probes.append(probe)
        return probe

    registry = DeltaAccountRegistry(repository, _TestOnlyProvider(), exchange_factory=factory)
    metadata = registry.register_account(
        tenant_id="tenant-phase344-wrong", label="wrong", region="INDIA",
        environment="SANDBOX", api_key="old-key", api_secret="old-secret",
    )
    repository.bind_provider_identity("tenant-phase344-wrong", metadata.account_id, "111111")
    before = repository.get("tenant-phase344-wrong", metadata.account_id)
    try:
        with pytest.raises(AccountScopeError, match="different Delta provider identity"):
            registry.rotate_credentials(
                tenant_id="tenant-phase344-wrong", account_id=metadata.account_id,
                api_key="other-user-key", api_secret="other-user-secret",
            )
        after = repository.get("tenant-phase344-wrong", metadata.account_id)
        assert after == before
        assert probes[0].close_calls == 1
    finally:
        repository.close()


def test_failed_authentication_does_not_replace_stored_credentials(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "failed-auth.sqlite3")
    probes = []

    def factory(**kwargs):
        probe = _IdentityProbe(None, failure=RuntimeError("sensitive transport detail"), **kwargs)
        probes.append(probe)
        return probe

    registry = DeltaAccountRegistry(repository, _TestOnlyProvider(), exchange_factory=factory)
    metadata = registry.register_account(
        tenant_id="tenant-phase344-fail", label="failed", region="INDIA",
        environment="SANDBOX", api_key="old-key", api_secret="old-secret",
    )
    before = repository.get("tenant-phase344-fail", metadata.account_id)
    try:
        with pytest.raises(CredentialVaultError, match="could not be authenticated") as error:
            registry.rotate_credentials(
                tenant_id="tenant-phase344-fail", account_id=metadata.account_id,
                api_key="bad-key", api_secret="bad-secret",
            )
        assert "sensitive transport detail" not in str(error.value)
        assert repository.get("tenant-phase344-fail", metadata.account_id) == before
        assert probes[0].close_calls == 1
    finally:
        repository.close()
