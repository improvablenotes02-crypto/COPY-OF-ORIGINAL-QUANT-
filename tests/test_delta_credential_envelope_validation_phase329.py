"""Phase 329: credential vault rejects malformed encryption envelopes without persistence."""
import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _MalformedProvider:
    def __init__(self, envelope=None, *, error=None):
        self.envelope = envelope
        self.error = error

    def encrypt(self, plaintext, *, associated_data):
        if self.error is not None:
            raise self.error
        return self.envelope

    def decrypt(self, envelope, *, associated_data):
        raise AssertionError("decrypt must not be called in this test")


@pytest.mark.parametrize(
    "envelope",
    [
        None,
        object(),
        CiphertextEnvelope("", "AES-256-GCM", b"ciphertext"),
        CiphertextEnvelope("key-1", "", b"ciphertext"),
        CiphertextEnvelope("key-1", "AES-256-GCM", b""),
        CiphertextEnvelope("key-1", "AES-256-GCM", "not-bytes"),
    ],
)
def test_malformed_encryption_envelope_is_rejected_before_repository_write(envelope):
    repository = SQLiteDeltaAccountRepository()
    registry = DeltaAccountRegistry(
        repository, _MalformedProvider(envelope=envelope),
    )
    try:
        with pytest.raises(CredentialVaultError, match="invalid ciphertext envelope"):
            registry.register_account(
                tenant_id="tenant-phase329", label="malformed",
                region="INDIA", environment="SANDBOX",
                api_key="sensitive-api-key",
                api_secret="sensitive-api-secret",
            )
        assert repository.list_for_tenant("tenant-phase329") == []
    finally:
        repository.close()


def test_encryption_provider_failure_is_sanitized_and_never_persists_credentials():
    secret_error = RuntimeError("provider leaked sensitive-api-secret in detail")
    repository = SQLiteDeltaAccountRepository()
    registry = DeltaAccountRegistry(
        repository, _MalformedProvider(error=secret_error),
    )
    try:
        with pytest.raises(CredentialVaultError, match="encryption failed") as caught:
            registry.register_account(
                tenant_id="tenant-phase329", label="provider-error",
                region="INDIA", environment="SANDBOX",
                api_key="sensitive-api-key",
                api_secret="sensitive-api-secret",
            )
        assert "sensitive-api-secret" not in str(caught.value)
        assert "sensitive-api-secret" not in repr(caught.value)
        assert repository.list_for_tenant("tenant-phase329") == []
    finally:
        repository.close()


def test_ciphertext_envelope_repr_does_not_disclose_ciphertext_bytes():
    envelope = CiphertextEnvelope("kms-key-7", "AES-256-GCM", b"credential-ciphertext")
    rendered = repr(envelope)
    assert "kms-key-7" in rendered
    assert "AES-256-GCM" in rendered
    assert "credential-ciphertext" not in rendered
