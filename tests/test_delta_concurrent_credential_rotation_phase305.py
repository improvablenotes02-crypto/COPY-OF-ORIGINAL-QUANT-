"""Phase 305: concurrent credential rotations are compare-and-swap serialized."""
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialRotationConflictError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
    _associated_data,
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


class _TenantIdentity:
    production_ready = False

    def authorize_tenant(self, tenant_id: str) -> bool:
        return tenant_id == "tenant-owner"

    def current_subject_id(self, tenant_id: str) -> str:
        if not self.authorize_tenant(tenant_id):
            raise PermissionError("tenant denied")
        return "owner-subject"


class _BarrierExchangeFactory:
    def __init__(self):
        self.barrier = threading.Barrier(2, timeout=10)
        self.created = []
        self.lock = threading.Lock()

    def __call__(self, *, api_key: str, api_secret: str, base_url: str):
        # Both rotations have already read the same generation before either
        # probe is allowed to complete and proceed to the repository CAS.
        self.barrier.wait()
        probe = _IdentityProbe(api_key, api_secret, base_url)
        with self.lock:
            self.created.append(probe)
        return probe


class _IdentityProbe:
    def __init__(self, api_key, api_secret, base_url):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.closed = False

    def _get_authenticated_account_id(self):
        return "123456"

    def close(self):
        self.closed = True


def test_two_concurrent_rotations_from_same_generation_commit_exactly_one():
    repository = SQLiteDeltaAccountRepository()
    encryption = _TestEncryptionProvider()
    exchange_factory = _BarrierExchangeFactory()
    registry = DeltaAccountRegistry(
        repository,
        encryption,
        exchange_factory=exchange_factory,
        tenant_authorizer=_TenantIdentity(),
    )
    try:
        account = registry.register_account(
            tenant_id="tenant-owner",
            label="Owner Delta",
            region="INDIA",
            environment="SANDBOX",
            api_key="initial-key",
            api_secret="initial-secret",
        )

        def rotate(suffix):
            return registry.rotate_credentials(
                tenant_id="tenant-owner",
                account_id=account.account_id,
                api_key=f"replacement-{suffix}",
                api_secret=f"secret-{suffix}",
            )

        outcomes = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(rotate, "a"), pool.submit(rotate, "b")]
            for future in futures:
                try:
                    outcomes.append(("committed", future.result(timeout=15)))
                except CredentialRotationConflictError as exc:
                    outcomes.append(("conflict", str(exc)))

        assert sorted(kind for kind, _ in outcomes) == ["committed", "conflict"]
        stored = repository.get("tenant-owner", account.account_id)
        assert stored is not None
        assert stored.credential_generation == 2

        plaintext = encryption.decrypt(
            CiphertextEnvelope(stored.key_id, stored.algorithm, stored.ciphertext),
            associated_data=_associated_data(stored),
        )
        persisted = json.loads(plaintext.decode("utf-8"))
        assert persisted["api_key"] in {"replacement-a", "replacement-b"}
        expected_suffix = persisted["api_key"].split("-")[-1]
        assert persisted["api_secret"] == f"secret-{expected_suffix}"

        events = repository.list_credential_rotation_events(
            "tenant-owner", account.account_id
        )
        assert len(events) == 1
        assert (events[0].previous_generation, events[0].new_generation) == (1, 2)
        assert events[0].event_hash
        assert len(exchange_factory.created) == 2
        assert all(probe.closed for probe in exchange_factory.created)
    finally:
        repository.close()
