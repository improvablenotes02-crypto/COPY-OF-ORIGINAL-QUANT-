"""Phase 340: credential rotation is atomic and revokes prior sessions."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialRotationConflictError,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestOnlyProvider:
    def __init__(self):
        self.rotation_barrier = None

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        if self.rotation_barrier is not None:
            self.rotation_barrier.wait(timeout=5)
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase340-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class FakeExchange:
    def __init__(self, **kwargs):
        self.api_key = kwargs["api_key"]
        self.api_secret = kwargs["api_secret"]
        self.balance_calls = 0

    def _get_authenticated_account_id(self):
        return "987654"

    def get_balance(self):
        self.balance_calls += 1
        return {"success": True}

    def close(self):
        pass


def make_registry(repository, provider, clients):
    def factory(**kwargs):
        client = FakeExchange(**kwargs)
        clients.append(client)
        return client
    return DeltaAccountRegistry(repository, provider, exchange_factory=factory)


def test_rotation_replaces_ciphertext_and_revokes_existing_session(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "rotation.sqlite3")
    provider = _TestOnlyProvider()
    clients = []
    registry = make_registry(repository, provider, clients)
    metadata = registry.register_account(
        tenant_id="tenant-phase340", label="rotation", region="INDIA",
        environment="SANDBOX", api_key="old-key", api_secret="old-secret",
    )
    old_session = registry.open_read_only_session(
        tenant_id="tenant-phase340", account_id=metadata.account_id
    )
    before = repository.get("tenant-phase340", metadata.account_id)
    try:
        rotated = registry.rotate_credentials(
            tenant_id="tenant-phase340", account_id=metadata.account_id,
            api_key="new-key", api_secret="new-secret",
        )
        after = repository.get("tenant-phase340", metadata.account_id)
        assert rotated.updated_at_ns > before.updated_at_ns
        assert after.key_id == "phase340-test-key"
        assert after.ciphertext != before.ciphertext
        assert after.provider_account_id == before.provider_account_id
        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            old_session.get_balance()
        assert clients[0].balance_calls == 0

        new_session = registry.open_read_only_session(
            tenant_id="tenant-phase340", account_id=metadata.account_id
        )
        try:
            assert clients[-1].api_key == "new-key"
            assert clients[-1].api_secret == "new-secret"
            assert new_session.get_balance() == {"success": True}
        finally:
            new_session.close()
    finally:
        old_session.close()
        repository.close()


def test_two_concurrent_rotations_use_compare_and_swap_and_only_one_wins(tmp_path):
    database = tmp_path / "concurrent-rotation.sqlite3"
    repository_a = SQLiteDeltaAccountRepository(database)
    repository_b = SQLiteDeltaAccountRepository(database)
    provider = _TestOnlyProvider()
    registry_a = make_registry(repository_a, provider, [])
    metadata = registry_a.register_account(
        tenant_id="tenant-phase340-race", label="race", region="INDIA",
        environment="SANDBOX", api_key="initial-key", api_secret="initial-secret",
    )
    registry_b = make_registry(repository_b, provider, [])
    provider.rotation_barrier = threading.Barrier(2)

    def rotate(registry, key):
        try:
            return registry.rotate_credentials(
                tenant_id="tenant-phase340-race", account_id=metadata.account_id,
                api_key=key, api_secret=key + "-secret",
            )
        except CredentialRotationConflictError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda pair: rotate(*pair),
                [(registry_a, "candidate-a"), (registry_b, "candidate-b")],
            ))
        assert sum(not isinstance(item, Exception) for item in results) == 1
        assert sum(isinstance(item, CredentialRotationConflictError) for item in results) == 1
        stored = repository_a.get("tenant-phase340-race", metadata.account_id)
        assert stored is not None
        assert stored.updated_at_ns > metadata.updated_at_ns
    finally:
        provider.rotation_barrier = None
        repository_b.close()
        repository_a.close()


def test_rotation_rejects_invalid_credentials_without_mutating_account(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "invalid-rotation.sqlite3")
    provider = _TestOnlyProvider()
    registry = make_registry(repository, provider, [])
    metadata = registry.register_account(
        tenant_id="tenant-phase340-invalid", label="invalid", region="INDIA",
        environment="SANDBOX", api_key="valid-key", api_secret="valid-secret",
    )
    before = repository.get("tenant-phase340-invalid", metadata.account_id)
    try:
        with pytest.raises(ValueError, match="api_key must be non-empty"):
            registry.rotate_credentials(
                tenant_id="tenant-phase340-invalid", account_id=metadata.account_id,
                api_key=" ", api_secret="replacement-secret",
            )
        after = repository.get("tenant-phase340-invalid", metadata.account_id)
        assert after == before
    finally:
        repository.close()


def test_rotation_fails_closed_when_repository_has_no_atomic_rotation_support():
    class ReadOnlyRepository:
        production_ready = False
        def __init__(self, record):
            self.record = record
        def get(self, tenant_id, account_id):
            return self.record if (tenant_id, account_id) == (self.record.tenant_id, self.record.account_id) else None

    provider = _TestOnlyProvider()
    backing = SQLiteDeltaAccountRepository()
    registry = make_registry(backing, provider, [])
    metadata = registry.register_account(
        tenant_id="tenant-phase340-unsupported", label="unsupported", region="INDIA",
        environment="SANDBOX", api_key="key", api_secret="secret",
    )
    record = backing.get("tenant-phase340-unsupported", metadata.account_id)
    backing.close()
    guarded = DeltaAccountRegistry(ReadOnlyRepository(record), provider)
    with pytest.raises(CredentialVaultError, match="does not support atomic credential rotation"):
        guarded.rotate_credentials(
            tenant_id="tenant-phase340-unsupported", account_id=metadata.account_id,
            api_key="replacement-key", api_secret="replacement-secret",
        )
