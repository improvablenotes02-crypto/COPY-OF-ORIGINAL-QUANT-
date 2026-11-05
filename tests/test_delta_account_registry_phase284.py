"""Phase 284: tenant-scoped encrypted Delta account registry."""
import hashlib

import pytest

from core.accounts.delta_account_registry import (
    AccountNotFoundError,
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class TestOnlyEncryptionProvider:
    """Deterministic test double; not suitable for production use."""

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        ciphertext = tag + bytes(value ^ 0xA5 for value in plaintext)
        return CiphertextEnvelope("test-only-key", "TEST-ONLY-XOR", ciphertext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])


def _registry(database=":memory:"):
    repository = SQLiteDeltaAccountRepository(database)
    registry = DeltaAccountRegistry(repository, TestOnlyEncryptionProvider())
    return registry, repository


def _register(registry, *, tenant="tenant-a", label="primary", region="INDIA", environment="SANDBOX"):
    return registry.register_account(
        tenant_id=tenant,
        label=label,
        region=region,
        environment=environment,
        api_key="api-key-secret-value",
        api_secret="api-secret-secret-value",
    )


def test_register_persists_ciphertext_only_and_returns_metadata():
    registry, repository = _registry()
    metadata = _register(registry)
    record = repository.get("tenant-a", metadata.account_id)
    assert record is not None
    assert b"api-key-secret-value" not in record.ciphertext
    assert b"api-secret-secret-value" not in record.ciphertext
    assert metadata.region == "INDIA"
    assert metadata.environment == "SANDBOX"
    assert not hasattr(metadata, "api_key")
    assert not hasattr(metadata, "api_secret")
    assert "api-secret-secret-value" not in repr(record)
    repository.close()


def test_tenant_scoping_prevents_cross_tenant_list_read_and_delete():
    registry, repository = _registry()
    owned = _register(registry, tenant="tenant-a")
    other = _register(registry, tenant="tenant-b", label="same-label")
    assert [item.account_id for item in registry.list_accounts("tenant-a")] == [owned.account_id]
    assert [item.account_id for item in registry.list_accounts("tenant-b")] == [other.account_id]
    with pytest.raises(AccountNotFoundError):
        registry.open_read_only_session(tenant_id="tenant-b", account_id=owned.account_id)
    assert registry.delete_account(tenant_id="tenant-b", account_id=owned.account_id) is False
    assert repository.get("tenant-a", owned.account_id) is not None
    assert registry.delete_account(tenant_id="tenant-a", account_id=owned.account_id) is True
    repository.close()


def test_read_only_session_pins_region_host_and_exposes_no_write_methods():
    registry, repository = _registry()
    metadata = _register(registry)
    session = registry.open_read_only_session(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    assert session.region == "INDIA"
    assert session.environment == "SANDBOX"
    assert session._exchange.rest.base_url == "https://cdn-ind.testnet.deltaex.org"
    assert not hasattr(session, "place_order")
    assert not hasattr(session, "cancel_order")
    assert not hasattr(session, "api_key")
    assert not hasattr(session, "api_secret")
    repository.close()


@pytest.mark.parametrize(
    "region,environment",
    [("MARS", "SANDBOX"), ("INDIA", "PAPER"), ("GLOBAL", "")],
)
def test_invalid_venue_scope_is_rejected_before_encryption(region, environment):
    registry, repository = _registry()
    with pytest.raises(ValueError):
        registry.register_account(
            tenant_id="tenant-a", label="x", region=region,
            environment=environment, api_key="key", api_secret="secret"
        )
    assert registry.list_accounts("tenant-a") == []
    repository.close()


def test_empty_credentials_are_rejected_without_persisting():
    registry, repository = _registry()
    with pytest.raises(ValueError, match="api_key"):
        registry.register_account(
            tenant_id="tenant-a", label="x", region="INDIA",
            environment="SANDBOX", api_key="", api_secret="secret"
        )
    with pytest.raises(ValueError, match="api_secret"):
        registry.register_account(
            tenant_id="tenant-a", label="x", region="INDIA",
            environment="SANDBOX", api_key="key", api_secret=""
        )
    assert registry.list_accounts("tenant-a") == []
    repository.close()


def test_authenticated_encryption_context_prevents_tenant_ciphertext_swapping():
    registry, repository = _registry()
    metadata = _register(registry, tenant="tenant-a")
    record = repository.get("tenant-a", metadata.account_id)
    swapped = type(record)(
        account_id=record.account_id, tenant_id="tenant-b", venue=record.venue,
        region=record.region, environment=record.environment, label=record.label,
        provider_account_id=None, key_id=record.key_id, algorithm=record.algorithm,
        ciphertext=record.ciphertext, created_at_ns=record.created_at_ns,
        updated_at_ns=record.updated_at_ns,
    )
    repository.save(swapped)
    with pytest.raises(CredentialVaultError):
        registry.open_read_only_session(tenant_id="tenant-b", account_id=metadata.account_id)
    repository.close()


def test_encrypted_registry_survives_repository_reopen(tmp_path):
    database = tmp_path / "accounts.sqlite3"
    registry, repository = _registry(database)
    metadata = _register(registry)
    repository.close()
    reopened = SQLiteDeltaAccountRepository(database)
    restored = DeltaAccountRegistry(reopened, TestOnlyEncryptionProvider())
    session = restored.open_read_only_session(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    assert session.region == "INDIA"
    assert session.environment == "SANDBOX"
    reopened.close()


def test_encryption_provider_failure_fails_closed():
    class BrokenProvider:
        def encrypt(self, plaintext, *, associated_data):
            raise RuntimeError("do not leak credential bytes")

        def decrypt(self, envelope, *, associated_data):
            raise RuntimeError("failure")

    repository = SQLiteDeltaAccountRepository()
    registry = DeltaAccountRegistry(repository, BrokenProvider())
    with pytest.raises(CredentialVaultError, match="encryption failed"):
        registry.register_account(
            tenant_id="tenant-a", label="x", region="INDIA",
            environment="SANDBOX", api_key="key", api_secret="secret"
        )
    assert registry.list_accounts("tenant-a") == []
    repository.close()
