"""Phase 330: modified persisted credential ciphertext fails closed before client creation."""
import hashlib

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _AuthenticatedTestProvider:
    """Deterministic test-only integrity envelope; never use outside tests."""

    def encrypt(self, plaintext, *, associated_data):
        tag = hashlib.sha256(associated_data + plaintext).digest()[:16]
        return CiphertextEnvelope(
            "test-key-330", "TEST-ONLY-INTEGRITY", tag + plaintext,
        )

    def decrypt(self, envelope, *, associated_data):
        if envelope.key_id != "test-key-330" or envelope.algorithm != "TEST-ONLY-INTEGRITY":
            raise ValueError("unexpected key metadata")
        if len(envelope.ciphertext) < 16:
            raise ValueError("truncated envelope")
        tag, plaintext = envelope.ciphertext[:16], envelope.ciphertext[16:]
        expected = hashlib.sha256(associated_data + plaintext).digest()[:16]
        if not hashlib.compare_digest(tag, expected):
            raise ValueError("ciphertext authentication failed")
        return plaintext


def _register(repository, factory):
    registry = DeltaAccountRegistry(
        repository, _AuthenticatedTestProvider(), exchange_factory=factory,
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase330", label="integrity-check",
        region="INDIA", environment="SANDBOX",
        api_key="phase330-api-key", api_secret="phase330-api-secret",
    )
    return registry, metadata


@pytest.mark.parametrize("mutation", ["flip-byte", "truncate", "wrong-key-id", "wrong-algorithm"])
def test_modified_credential_envelope_fails_before_exchange_factory(mutation):
    repository = SQLiteDeltaAccountRepository()
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        raise AssertionError("exchange factory must not receive unauthenticated credentials")

    registry, metadata = _register(repository, factory)
    try:
        record = repository.get("tenant-phase330", metadata.account_id)
        ciphertext = bytearray(record.ciphertext)
        key_id, algorithm = record.key_id, record.algorithm
        if mutation == "flip-byte":
            ciphertext[-1] ^= 0x01
        elif mutation == "truncate":
            ciphertext = ciphertext[:8]
        elif mutation == "wrong-key-id":
            key_id = "attacker-selected-key"
        elif mutation == "wrong-algorithm":
            algorithm = "PLAINTEXT"
        repository._connection.execute(
            "UPDATE delta_accounts SET key_id = ?, algorithm = ?, ciphertext = ? "
            "WHERE tenant_id = ? AND account_id = ?",
            (key_id, algorithm, bytes(ciphertext), "tenant-phase330", metadata.account_id),
        )

        with pytest.raises(CredentialVaultError, match="decryption or validation failed"):
            registry.open_read_only_session(
                tenant_id="tenant-phase330", account_id=metadata.account_id,
            )
        assert factory_calls == []
    finally:
        repository.close()


def test_credential_payload_with_extra_fields_is_rejected_before_client_creation():
    class InvalidPayloadProvider:
        def encrypt(self, plaintext, *, associated_data):
            return CiphertextEnvelope("invalid-payload-key", "TEST-ONLY", b"opaque")

        def decrypt(self, envelope, *, associated_data):
            return b'{"api_key":"key","api_secret":"secret","extra":"unexpected"}'

    repository = SQLiteDeltaAccountRepository()
    factory_calls = []
    registry = DeltaAccountRegistry(
        repository, InvalidPayloadProvider(),
        exchange_factory=lambda **kwargs: factory_calls.append(kwargs),
    )
    try:
        metadata = registry.register_account(
            tenant_id="tenant-phase330", label="extra-field",
            region="INDIA", environment="SANDBOX",
            api_key="key", api_secret="secret",
        )
        with pytest.raises(CredentialVaultError, match="decryption or validation failed"):
            registry.open_read_only_session(
                tenant_id="tenant-phase330", account_id=metadata.account_id,
            )
        assert factory_calls == []
    finally:
        repository.close()
