"""Phase 306: account deletion wins safely over an in-flight credential rotation."""
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.accounts.delta_account_registry import (
    AccountNotFoundError,
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


class _TenantIdentity:
    production_ready = False

    def authorize_tenant(self, tenant_id: str) -> bool:
        return tenant_id == "tenant-owner"

    def current_subject_id(self, tenant_id: str) -> str:
        if not self.authorize_tenant(tenant_id):
            raise PermissionError("tenant denied")
        return "owner-subject"


class _PausedIdentityProbe:
    def __init__(self, entered: threading.Event, release: threading.Event):
        self.entered = entered
        self.release = release
        self.closed = False

    def _get_authenticated_account_id(self):
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test did not release the identity probe")
        return "123456"

    def close(self):
        self.closed = True


def test_account_deletion_during_rotation_cannot_resurrect_account_or_audit_event():
    repository = SQLiteDeltaAccountRepository()
    entered = threading.Event()
    release = threading.Event()
    probes = []

    def exchange_factory(*, api_key: str, api_secret: str, base_url: str):
        probe = _PausedIdentityProbe(entered, release)
        probes.append(probe)
        return probe

    registry = DeltaAccountRegistry(
        repository,
        _TestEncryptionProvider(),
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

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                registry.rotate_credentials,
                tenant_id="tenant-owner",
                account_id=account.account_id,
                api_key="replacement-key",
                api_secret="replacement-secret",
            )
            assert entered.wait(timeout=10), "rotation never reached identity probe"

            # Delete after rotation has captured generation 1, but before its
            # compare-and-swap can commit the replacement ciphertext.
            assert registry.delete_account(
                tenant_id="tenant-owner", account_id=account.account_id
            ) is True
            release.set()

            with pytest.raises(AccountNotFoundError):
                future.result(timeout=15)

        assert repository.get("tenant-owner", account.account_id) is None
        assert registry.list_accounts("tenant-owner") == []
        # The rotation transaction must not append an event for a deleted row.
        assert repository.list_credential_rotation_events(
            "tenant-owner", account.account_id
        ) == []
        assert len(probes) == 1
        assert probes[0].closed is True
    finally:
        release.set()
        repository.close()
