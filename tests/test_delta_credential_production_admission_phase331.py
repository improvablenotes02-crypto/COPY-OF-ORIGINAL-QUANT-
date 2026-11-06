"""Phase 331: production credential security admission fails closed."""

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        return CiphertextEnvelope("test-key", "TEST-ONLY", b"opaque-ciphertext")

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        return b\'{"api_key":"key","api_secret":"secret"}\'


class _DeclaredProductionProvider(_TestOnlyProvider):
    # Admission-contract test double only; not a cryptographic implementation.
    production_ready = True
    algorithm = "AES-256-GCM"

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        return CiphertextEnvelope("test-kms-key", self.algorithm, b"opaque-test-ciphertext")


def test_production_mode_rejects_test_provider_and_local_sqlite_repository():
    repository = SQLiteDeltaAccountRepository()
    try:
        with pytest.raises(CredentialVaultError, match="production credential security"):
            DeltaAccountRegistry(repository, _TestOnlyProvider(), require_production_security=True)
        with pytest.raises(CredentialVaultError, match="production credential security"):
            DeltaAccountRegistry(repository, _DeclaredProductionProvider(), require_production_security=True)
    finally:
        repository.close()


def test_production_security_flag_must_be_a_boolean():
    repository = SQLiteDeltaAccountRepository()
    try:
        with pytest.raises(ValueError, match="must be a boolean"):
            DeltaAccountRegistry(repository, _TestOnlyProvider(), require_production_security="yes")
    finally:
        repository.close()


def test_production_gate_is_opt_in_and_does_not_break_sandbox_registry():
    repository = SQLiteDeltaAccountRepository()
    try:
        registry = DeltaAccountRegistry(repository, _TestOnlyProvider())
        metadata = registry.register_account(
            tenant_id="tenant-phase331", label="sandbox", region="INDIA",
            environment="SANDBOX", api_key="test-api-key", api_secret="test-api-secret",
        )
        assert registry.list_accounts("tenant-phase331") == [metadata]
    finally:
        repository.close()
