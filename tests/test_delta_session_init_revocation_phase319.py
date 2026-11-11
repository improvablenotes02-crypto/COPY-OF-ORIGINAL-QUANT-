"""Phase 319: reject session creation if authorization changes during factory init."""
import json

import pytest

from core.accounts.delta_account_registry import (
    CredentialVaultError,
    DeltaAccountRegistry,
    EncryptedDeltaAccount,
)


class FakeEncryptionProvider:
    def decrypt(self, envelope, *, associated_data):
        return json.dumps({"api_key": "test-key", "api_secret": "test-secret"}).encode()


class SingleAccountRepository:
    def __init__(self, record):
        self.record = record

    def get(self, tenant_id, account_id):
        if tenant_id == self.record.tenant_id and account_id == self.record.account_id:
            return self.record
        return None


class RevocableTenantAuthorizer:
    def __init__(self):
        self.allowed = True

    def authorize_tenant(self, tenant_id):
        return self.allowed


class ClosableExchange:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_session_not_published_if_tenant_revoked_during_exchange_init():
    record = EncryptedDeltaAccount(
        account_id="internal-account",
        tenant_id="tenant-owner",
        venue="delta",
        region="INDIA",
        environment="SANDBOX",
        label="Owner Delta",
        provider_account_id=None,
        key_id="test-key-id",
        algorithm="TEST-ONLY",
        ciphertext=b"test-only-ciphertext",
        created_at_ns=1,
        updated_at_ns=1,
    )
    authorizer = RevocableTenantAuthorizer()
    exchange = ClosableExchange()

    def exchange_factory(**kwargs):
        authorizer.allowed = False
        return exchange

    registry = DeltaAccountRegistry(
        SingleAccountRepository(record),
        FakeEncryptionProvider(),
        exchange_factory=exchange_factory,
        tenant_authorizer=authorizer,
    )

    with pytest.raises(CredentialVaultError, match="authorization changed during initialization"):
        registry.open_read_only_session(
            tenant_id="tenant-owner",
            account_id="internal-account",
        )

    assert exchange.closed is True
