"""Phase 285: bind each tenant-scoped account to authenticated Delta identity."""
import pytest

from core.accounts.delta_account_registry import (
    AccountNotFoundError,
    AccountScopeError,
    CiphertextEnvelope,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class TestOnlyEncryptionProvider:
    """Deterministic test double; not suitable for production use."""

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        import hashlib
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("test-only-key", "TEST-ONLY-XOR", tag + bytes(x ^ 0xA5 for x in plaintext))

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        import hashlib
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(x ^ 0xA5 for x in envelope.ciphertext[16:])


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


def _registry(provider_id="57354187"):
    repository = SQLiteDeltaAccountRepository()
    registry = DeltaAccountRegistry(
        repository,
        TestOnlyEncryptionProvider(),
        exchange_factory=lambda **kwargs: FakeDeltaExchange(
            **kwargs, provider_id=provider_id
        ),
    )
    return registry, repository


def _register(registry, tenant="tenant-a"):
    return registry.register_account(
        tenant_id=tenant,
        label="primary",
        region="INDIA",
        environment="SANDBOX",
        api_key="local-test-key",
        api_secret="local-test-secret",
    )


def test_authenticated_identity_is_bound_once_to_tenant_account():
    registry, repository = _registry()
    metadata = _register(registry)
    bound = registry.verify_and_bind_identity(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    assert bound.provider_account_id == "57354187"
    assert repository.get("tenant-a", metadata.account_id).provider_account_id == "57354187"
    assert registry.verify_and_bind_identity(
        tenant_id="tenant-a", account_id=metadata.account_id
    ).provider_account_id == "57354187"
    repository.close()


def test_provider_identity_mismatch_cannot_overwrite_existing_binding():
    registry, repository = _registry(provider_id="222")
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
    registry, repository = _registry(provider_id=provider_id)
    metadata = _register(registry)
    with pytest.raises(AccountScopeError, match="missing or invalid"):
        registry.verify_and_bind_identity(
            tenant_id="tenant-a", account_id=metadata.account_id
        )
    assert repository.get("tenant-a", metadata.account_id).provider_account_id is None
    repository.close()


def test_identity_binding_cannot_be_invoked_through_another_tenant():
    calls = []
    repository = SQLiteDeltaAccountRepository()
    def factory(**kwargs):
        calls.append(True)
        return FakeDeltaExchange(**kwargs)
    registry = DeltaAccountRegistry(
        repository, TestOnlyEncryptionProvider(), exchange_factory=factory
    )
    metadata = _register(registry, tenant="tenant-a")
    with pytest.raises(AccountNotFoundError):
        registry.verify_and_bind_identity(
            tenant_id="tenant-b", account_id=metadata.account_id
        )
    assert calls == []
    repository.close()


def test_history_snapshot_identity_must_match_bound_provider_account():
    registry, repository = _registry(provider_id="999")
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
