"""Phase 318: account-list results must not escape after tenant revocation."""
import threading

from core.accounts.delta_account_registry import (
    AccountScopeError,
    DeltaAccountRegistry,
    EncryptedDeltaAccount,
)


class BlockingListRepository:
    def __init__(self, record):
        self.record = record
        self.started = threading.Event()
        self.release = threading.Event()

    def list_for_tenant(self, tenant_id):
        self.started.set()
        assert self.release.wait(2)
        return [self.record]


class RevocableTenantAuthorizer:
    def __init__(self):
        self.allowed = True

    def authorize_tenant(self, tenant_id):
        return self.allowed


def test_account_list_rejects_metadata_after_mid_read_revocation():
    record = EncryptedDeltaAccount(
        account_id="internal-account",
        tenant_id="tenant-owner",
        venue="delta",
        region="INDIA",
        environment="SANDBOX",
        label="Owner Delta",
        provider_account_id="12345",
        key_id="test-key",
        algorithm="TEST-ONLY",
        ciphertext=b"test-only-ciphertext",
        created_at_ns=1,
        updated_at_ns=1,
    )
    repository = BlockingListRepository(record)
    authorizer = RevocableTenantAuthorizer()
    registry = DeltaAccountRegistry(
        repository, object(), tenant_authorizer=authorizer
    )
    results = []
    errors = []

    def list_accounts():
        try:
            results.extend(registry.list_accounts("tenant-owner"))
        except Exception as exc:
            errors.append(exc)

    reader = threading.Thread(target=list_accounts)
    reader.start()
    assert repository.started.wait(1)
    authorizer.allowed = False
    repository.release.set()
    reader.join(1)

    assert not reader.is_alive()
    assert results == []
    assert len(errors) == 1
    assert isinstance(errors[0], AccountScopeError)
    assert "not authorized" in str(errors[0])
