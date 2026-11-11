"""Phase 310: reject account data returned after read-session authorization changes."""
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestEncryption:
    def encrypt(self, plaintext, *, associated_data):
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope(
            "test-only-key", "TEST-ONLY-XOR",
            tag + bytes(value ^ 0xA5 for value in plaintext),
        )

    def decrypt(self, envelope, *, associated_data):
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])


class _MutableIdentity:
    production_ready = False

    def __init__(self):
        self.subject_id = "owner-subject"

    def authorize_tenant(self, tenant_id):
        return tenant_id == "tenant-owner"

    def current_subject_id(self, tenant_id):
        if not self.authorize_tenant(tenant_id):
            raise PermissionError("tenant denied")
        return self.subject_id


class _OwnerApproval:
    production_ready = False

    def is_approved(self, **kwargs):
        return False

    def is_approved_for_subject(self, *, subject_id, **kwargs):
        return subject_id == "owner-subject"


class _PausedAccountRead:
    def __init__(self, entered, release):
        self.entered = entered
        self.release = release
        self.calls = []
        self.closed = False

    def _read(self, name):
        self.calls.append(name)
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test did not release account read")
        return {"success": True, "result": []}

    def get_balance(self):
        return self._read("balance")

    def get_positions(self):
        return self._read("positions")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("method_name", ["get_balance", "get_positions"])
def test_subject_change_during_account_read_prevents_stale_data_return(method_name):
    repository = SQLiteDeltaAccountRepository()
    identity = _MutableIdentity()
    entered, release, exchanges = threading.Event(), threading.Event(), []

    def exchange_factory(**kwargs):
        exchange = _PausedAccountRead(entered, release)
        exchanges.append(exchange)
        return exchange

    registry = DeltaAccountRegistry(
        repository,
        _TestEncryption(),
        exchange_factory=exchange_factory,
        tenant_authorizer=identity,
        credential_approval_provider=_OwnerApproval(),
    )
    session = None
    try:
        account = registry.register_account(
            tenant_id="tenant-owner",
            label="Owner Delta",
            region="INDIA",
            environment="SANDBOX",
            api_key="owner-key",
            api_secret="owner-secret",
        )
        session = registry.open_read_only_session(
            tenant_id="tenant-owner", account_id=account.account_id
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(getattr(session, method_name))
            assert entered.wait(timeout=10), "account read did not start"
            identity.subject_id = "member-subject"
            release.set()
            with pytest.raises(CredentialVaultError, match="no longer authorized"):
                future.result(timeout=15)

        assert exchanges[0].calls == [method_name.removeprefix("get_")]
    finally:
        release.set()
        if session is not None:
            session.close()
        assert not exchanges or exchanges[0].closed
        repository.close()
