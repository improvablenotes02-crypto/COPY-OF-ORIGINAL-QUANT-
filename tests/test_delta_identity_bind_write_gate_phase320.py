"""Phase 320: authorization is rechecked inside the identity-binding write gate."""
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


class RevocableAuthorizer:
    def __init__(self):
        self.allowed = True

    def authorize_tenant(self, tenant_id):
        return self.allowed


class FakeExchange:
    def _get_authenticated_account_id(self):
        return "123456"


class BlockingSQLiteRepository(SQLiteDeltaAccountRepository):
    def __init__(self):
        super().__init__(":memory:")
        self.bind_entered = threading.Event()
        self.allow_bind = threading.Event()

    def bind_provider_identity(self, *args, **kwargs):
        # Simulate revocation in the gap after the venue identity is verified
        # but before the repository reaches its in-lock authorization callback.
        self.bind_entered.set()
        assert self.allow_bind.wait(timeout=3), "test did not release identity bind"
        return super().bind_provider_identity(*args, **kwargs)


def test_revocation_after_venue_verification_prevents_identity_persistence():
    repository = BlockingSQLiteRepository()
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
        updated_at_ns=10,
        credential_generation=1,
    )
    repository.save(record)
    authorizer = RevocableAuthorizer()
    registry = DeltaAccountRegistry(
        repository,
        FakeEncryptionProvider(),
        exchange_factory=lambda **kwargs: FakeExchange(),
        tenant_authorizer=authorizer,
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
    authorizer.allowed = False
    repository.allow_bind.set()
    worker.join(timeout=3)

    assert not worker.is_alive(), "identity binding worker did not terminate"
    assert len(failures) == 1
    assert isinstance(failures[0], AccountScopeError)
    saved = repository.get("tenant-owner", "internal-account")
    assert saved is not None
    assert saved.provider_account_id is None
    assert saved.updated_at_ns == 10


def test_sqlite_write_reservation_serializes_other_repository_connections(tmp_path):
    database = tmp_path / "shared-delta-accounts.sqlite3"
    writer = SQLiteDeltaAccountRepository(database)
    competing_writer = SQLiteDeltaAccountRepository(database)
    writer.save(
        EncryptedDeltaAccount(
            account_id="cross-connection-account",
            tenant_id="tenant-owner",
            venue="delta",
            region="INDIA",
            environment="SANDBOX",
            label="Cross connection",
            provider_account_id=None,
            key_id="test-key-id",
            algorithm="TEST-ONLY",
            ciphertext=b"test-only-ciphertext",
            created_at_ns=1,
            updated_at_ns=10,
            credential_generation=1,
        )
    )
    authorization_entered = threading.Event()
    release_authorization = threading.Event()
    delete_started = threading.Event()
    delete_finished = threading.Event()
    bind_errors = []
    delete_results = []

    def authorization_check():
        authorization_entered.set()
        assert release_authorization.wait(timeout=3)
        return True

    def bind():
        try:
            writer.bind_provider_identity(
                "tenant-owner",
                "cross-connection-account",
                "123456",
                expected_generation=1,
                expected_updated_at_ns=10,
                authorization_check=authorization_check,
            )
        except Exception as exc:
            bind_errors.append(exc)

    def delete():
        delete_started.set()
        delete_results.append(
            competing_writer.delete("tenant-owner", "cross-connection-account")
        )
        delete_finished.set()

    bind_thread = threading.Thread(target=bind)
    delete_thread = threading.Thread(target=delete)
    bind_thread.start()
    assert authorization_entered.wait(timeout=3)
    delete_thread.start()
    assert delete_started.wait(timeout=3)
    # A second SQLite connection must wait for the identity-binding transaction.
    assert not delete_finished.wait(timeout=0.2)
    release_authorization.set()
    bind_thread.join(timeout=3)
    delete_thread.join(timeout=3)

    assert not bind_thread.is_alive()
    assert not delete_thread.is_alive()
    assert bind_errors == []
    assert delete_results == [True]
    assert delete_finished.is_set()
    writer.close()
    competing_writer.close()
