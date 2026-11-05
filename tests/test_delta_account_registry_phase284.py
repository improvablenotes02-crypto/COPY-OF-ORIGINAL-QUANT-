"""Phase 284: tenant-scoped encrypted Delta account registry."""
import hashlib

import pytest

from core.accounts.delta_account_registry import (
    AccountNotFoundError,
    AccountScopeError,
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


class FakeDeltaExchange:
    def __init__(self, *, api_key, api_secret, base_url, provider_id="57354187"):
        self.provider_id = provider_id
        self.base_url = base_url

    def _get_authenticated_account_id(self):
        return self.provider_id

    def get_order_history_snapshot(self, *, max_pages=100):
        return {"account_id": self.provider_id, "orders": []}

    def get_fill_history_snapshot(self, *, max_pages=100):
        return {"account_id": self.provider_id, "fills": []}


def _registry(database=":memory:", exchange_factory=None):
    repository = SQLiteDeltaAccountRepository(database)
    registry = DeltaAccountRegistry(
        repository, TestOnlyEncryptionProvider(),
        exchange_factory=exchange_factory,
    )
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
    # Simulate an operator/database-level row swap. The AEAD context
    # still binds the ciphertext to tenant-a, so tenant-b cannot decrypt it.
    repository._connection.execute(
        "UPDATE delta_accounts SET tenant_id = ? WHERE account_id = ?",
        ("tenant-b", metadata.account_id),
    )
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


def test_authenticated_identity_is_bound_once_to_tenant_account():
    registry, repository = _registry(
        exchange_factory=lambda **kwargs: FakeDeltaExchange(**kwargs)
    )
    metadata = _register(registry)
    bound = registry.verify_and_bind_identity(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    assert bound.provider_account_id == "57354187"
    assert repository.get("tenant-a", metadata.account_id).provider_account_id == "57354187"
    # Same provider identity is idempotent; a second check cannot rebind it.
    assert registry.verify_and_bind_identity(
        tenant_id="tenant-a", account_id=metadata.account_id
    ).provider_account_id == "57354187"
    repository.close()


def test_provider_identity_mismatch_cannot_overwrite_existing_binding():
    registry, repository = _registry(
        exchange_factory=lambda **kwargs: FakeDeltaExchange(**kwargs, provider_id="222")
    )
    metadata = _register(registry)
    repository.bind_provider_identity("tenant-a", metadata.account_id, "111")
    with pytest.raises(AccountScopeError, match="does not match"):
        registry.verify_and_bind_identity(
            tenant_id="tenant-a", account_id=metadata.account_id
        )
    assert repository.get("tenant-a", metadata.account_id).provider_account_id == "111"
    repository.close()


@pytest.mark.parametrize("provider_id", ["", "0", "-1", "not-an-id"])
def test_invalid_provider_identity_is_never_bound(provider_id):
    registry, repository = _registry(
        exchange_factory=lambda **kwargs: FakeDeltaExchange(**kwargs, provider_id=provider_id)
    )
    metadata = _register(registry)
    with pytest.raises(AccountScopeError, match="missing or invalid"):
        registry.verify_and_bind_identity(
            tenant_id="tenant-a", account_id=metadata.account_id
        )
    assert repository.get("tenant-a", metadata.account_id).provider_account_id is None
    repository.close()


def test_identity_binding_cannot_be_invoked_through_another_tenant():
    called = []
    def factory(**kwargs):
        called.append(True)
        return FakeDeltaExchange(**kwargs)
    registry, repository = _registry(exchange_factory=factory)
    metadata = _register(registry, tenant="tenant-a")
    with pytest.raises(AccountNotFoundError):
        registry.verify_and_bind_identity(
            tenant_id="tenant-b", account_id=metadata.account_id
        )
    assert called == []
    repository.close()


def test_history_snapshot_identity_must_match_bound_provider_account():
    registry, repository = _registry(
        exchange_factory=lambda **kwargs: FakeDeltaExchange(**kwargs, provider_id="999")
    )
    metadata = _register(registry)
    repository.bind_provider_identity("tenant-a", metadata.account_id, "123")
    session = registry.open_read_only_session(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    with pytest.raises(AccountScopeError, match="snapshot identity"):
        session.get_order_history_snapshot()
    with pytest.raises(AccountScopeError, match="snapshot identity"):
        session.get_fill_history_snapshot()
    repository.close()
