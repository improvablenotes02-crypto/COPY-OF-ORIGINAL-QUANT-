"""Phase 321: identity binding revalidates owner approval inside the write gate."""
import json
import threading

import pytest

from core.accounts.delta_account_registry import (
    AccountScopeError,
    DeltaAccountRegistry,
    EncryptedDeltaAccount,
    SQLiteDeltaAccountRepository,
)


class FakeEncryptionProvider:
    def decrypt(self, envelope, *, associated_data):
        return json.dumps({"api_key": "test-key", "api_secret": "test-secret"}).encode()


class SubjectAuthorizer:
    def __init__(self):
        self.allowed = True

    def authorize_tenant(self, tenant_id):
        return self.allowed

    def current_subject_id(self, tenant_id):
        return "owner-subject"


class RevocableApprovalProvider:
    def __init__(self):
        self.approved = True

    def is_approved(self, *, tenant_id, account_id, fingerprint):
        return self.approved

    def is_approved_for_subject(
        self, *, tenant_id, account_id, fingerprint, subject_id
    ):
        return self.approved and subject_id == "owner-subject"


class FakeExchange:
    def _get_authenticated_account_id(self):
        return "123456"


class BlockingSQLiteRepository(SQLiteDeltaAccountRepository):
    def __init__(self):
        super().__init__(":memory:")
        self.bind_entered = threading.Event()
        self.allow_bind = threading.Event()
        self.after_bind = None

    def bind_provider_identity(self, *args, **kwargs):
        self.bind_entered.set()
        assert self.allow_bind.wait(timeout=3), "test did not release identity bind"
        result = super().bind_provider_identity(*args, **kwargs)
        if self.after_bind is not None:
            self.after_bind()
        return result


def test_approval_revocation_after_venue_verification_prevents_identity_persistence():
    repository = BlockingSQLiteRepository()
    repository.save(
        EncryptedDeltaAccount(
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
            updated_at_ns=10,
            credential_generation=1,
        )
    )
    approval = RevocableApprovalProvider()
    registry = DeltaAccountRegistry(
        repository,
        FakeEncryptionProvider(),
        exchange_factory=lambda **kwargs: FakeExchange(),
        tenant_authorizer=SubjectAuthorizer(),
        credential_approval_provider=approval,
    )
    failures = []

    def bind_identity():
        try:
            registry.verify_and_bind_identity(
                tenant_id="tenant-owner",
                account_id="internal-account",
            )
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=bind_identity)
    worker.start()
    assert repository.bind_entered.wait(timeout=3), "identity binding did not reach repository"
    approval.approved = False
    repository.allow_bind.set()
    worker.join(timeout=3)

    assert not worker.is_alive(), "identity binding worker did not terminate"
    assert len(failures) == 1
    assert isinstance(failures[0], AccountScopeError)
    saved = repository.get("tenant-owner", "internal-account")
    assert saved is not None
    assert saved.provider_account_id is None
    assert saved.updated_at_ns == 10
    repository.close()



def test_revocation_after_identity_commit_prevents_metadata_return():
    repository = BlockingSQLiteRepository()
    repository.save(
        EncryptedDeltaAccount(
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
            updated_at_ns=10,
            credential_generation=1,
        )
    )
    approval = RevocableApprovalProvider()
    registry = DeltaAccountRegistry(
        repository,
        FakeEncryptionProvider(),
        exchange_factory=lambda **kwargs: FakeExchange(),
        tenant_authorizer=SubjectAuthorizer(),
        credential_approval_provider=approval,
    )
    repository.allow_bind.set()
    repository.after_bind = lambda: setattr(approval, "approved", False)

    with pytest.raises(AccountScopeError):
        registry.verify_and_bind_identity(
            tenant_id="tenant-owner",
            account_id="internal-account",
        )

    # The repository commit already happened, but no stale metadata is returned.
    saved = repository.get("tenant-owner", "internal-account")
    assert saved is not None
    assert saved.provider_account_id == "123456"
    assert saved.updated_at_ns > 10
    repository.close()
