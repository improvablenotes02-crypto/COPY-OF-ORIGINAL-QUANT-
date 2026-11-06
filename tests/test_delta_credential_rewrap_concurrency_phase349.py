"""Phase 349: concurrent encryption-key rewraps are serialized without retry."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialRotationConflictError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _RotatingProvider:
    def __init__(self):
        self.active_key_id = "key-v1"
        self.barrier = None

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope(self.active_key_id, "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


def test_two_concurrent_rewraps_commit_one_generation_and_one_audit_event(tmp_path):
    database = tmp_path / "concurrent-rewrap.sqlite3"
    repository_a = SQLiteDeltaAccountRepository(database)
    repository_b = SQLiteDeltaAccountRepository(database)
    provider = _RotatingProvider()
    registry_a = DeltaAccountRegistry(repository_a, provider)
    metadata = registry_a.register_account(
        tenant_id="tenant-phase349", label="concurrent-rewrap", region="INDIA",
        environment="SANDBOX", api_key="stable-key", api_secret="stable-secret",
    )
    registry_b = DeltaAccountRegistry(repository_b, provider)
    provider.active_key_id = "key-v2"
    provider.barrier = threading.Barrier(2)

    def rewrap(registry):
        try:
            return registry.rewrap_credentials(
                tenant_id="tenant-phase349", account_id=metadata.account_id
            )
        except CredentialRotationConflictError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(rewrap, [registry_a, registry_b]))
        assert sum(not isinstance(item, Exception) for item in results) == 1
        assert sum(isinstance(item, CredentialRotationConflictError) for item in results) == 1
        stored = repository_a.get("tenant-phase349", metadata.account_id)
        assert stored.key_id == "key-v2"
        assert stored.credential_generation == 2
        events = repository_a.list_credential_rotation_events(
            "tenant-phase349", metadata.account_id
        )
        assert len(events) == 1
        assert events[0].previous_key_id == "key-v1"
        assert events[0].new_key_id == "key-v2"
    finally:
        provider.barrier = None
        repository_b.close()
        repository_a.close()
