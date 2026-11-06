"""Phase 332: client-construction exceptions cannot disclose Delta credentials."""

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        return CiphertextEnvelope("test-key", "TEST-ONLY", b"opaque")

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        return b'{"api_key":"phase332-key","api_secret":"phase332-secret"}'


def test_exchange_factory_exception_is_sanitized_before_leaving_registry():
    repository = SQLiteDeltaAccountRepository()
    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        raise RuntimeError("constructor echoed phase332-secret and phase332-key")

    registry = DeltaAccountRegistry(repository, _TestProvider(), exchange_factory=factory)
    try:
        metadata = registry.register_account(
            tenant_id="tenant-phase332", label="redaction", region="INDIA",
            environment="SANDBOX", api_key="phase332-key", api_secret="phase332-secret",
        )
        with pytest.raises(CredentialVaultError, match="client initialization failed") as caught:
            registry.open_read_only_session(
                tenant_id="tenant-phase332", account_id=metadata.account_id,
            )
        assert len(seen) == 1
        assert seen[0]["api_key"] == "phase332-key"
        assert seen[0]["api_secret"] == "phase332-secret"
        assert "phase332-key" not in str(caught.value)
        assert "phase332-secret" not in str(caught.value)
        assert "phase332-secret" not in repr(caught.value)
    finally:
        repository.close()
