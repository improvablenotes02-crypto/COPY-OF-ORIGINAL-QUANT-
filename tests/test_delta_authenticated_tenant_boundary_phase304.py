"""Phase 304: authenticated tenant identity fences every registry operation."""
import hashlib

import pytest

from core.accounts.delta_account_registry import (
    AccountScopeError,
    CiphertextEnvelope,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestEncryptionProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope(
            "test-only-key", "TEST-ONLY-XOR",
            tag + bytes(value ^ 0xA5 for value in plaintext),
        )

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])


class _TrustedIdentity:
    production_ready = False

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.authorization_calls = []

    def authorize_tenant(self, tenant_id: str) -> bool:
        self.authorization_calls.append(tenant_id)
        return tenant_id == self.tenant_id

    def current_subject_id(self, tenant_id: str) -> str:
        if not self.authorize_tenant(tenant_id):
            raise PermissionError("tenant denied")
        return self.tenant_id + "-owner"


class _ExchangeFactory:
    instances = []

    def __call__(self, *, api_key: str, api_secret: str, base_url: str):
        instance = _ReadOnlyProbe(api_key, api_secret, base_url)
        self.instances.append(instance)
        return instance


class _ReadOnlyProbe:
    def __init__(self, api_key, api_secret, base_url):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.closed = False

    def _get_authenticated_account_id(self):
        return "123456"

    def close(self):
        self.closed = True


def test_authenticated_tenant_switch_blocks_cross_tenant_read_rotate_and_delete():
    repository = SQLiteDeltaAccountRepository()
    identity = _TrustedIdentity("tenant-a")
    exchange_factory = _ExchangeFactory()
    exchange_factory.instances.clear()
    registry = DeltaAccountRegistry(
        repository,
        _TestEncryptionProvider(),
        exchange_factory=exchange_factory,
        tenant_authorizer=identity,
    )
    try:
        account = registry.register_account(
            tenant_id="tenant-a",
            label="Tenant A private Delta account",
            region="INDIA",
            environment="SANDBOX",
            api_key="tenant-a-key",
            api_secret="tenant-a-secret",
        )
        assert [item.account_id for item in registry.list_accounts("tenant-a")] == [
            account.account_id
        ]
        assert repository.get("tenant-a", account.account_id) is not None

        # The same registry object now observes a different verified principal.
        identity.tenant_id = "tenant-b"
        with pytest.raises(AccountScopeError, match="tenant is not authorized"):
            registry.list_accounts("tenant-a")
        with pytest.raises(AccountScopeError, match="tenant is not authorized"):
            registry.open_read_only_session(
                tenant_id="tenant-a", account_id=account.account_id
            )
        with pytest.raises(AccountScopeError, match="tenant is not authorized"):
            registry.rotate_credentials(
                tenant_id="tenant-a",
                account_id=account.account_id,
                api_key="attacker-key",
                api_secret="attacker-secret",
            )
        with pytest.raises(AccountScopeError, match="tenant is not authorized"):
            registry.delete_account(
                tenant_id="tenant-a", account_id=account.account_id
            )
        with pytest.raises(AccountScopeError, match="tenant is not authorized"):
            registry.register_account(
                tenant_id="tenant-a",
                label="unauthorized",
                region="INDIA",
                environment="SANDBOX",
                api_key="attacker-key",
                api_secret="attacker-secret",
            )

        # Denied operations must not reach the exchange constructor or mutate
        # the owner's stored credential generation/ciphertext.
        assert exchange_factory.instances == []
        stored = repository.get("tenant-a", account.account_id)
        assert stored is not None
        assert stored.credential_generation == 1
        assert repository.list_for_tenant("tenant-b") == []
    finally:
        repository.close()
