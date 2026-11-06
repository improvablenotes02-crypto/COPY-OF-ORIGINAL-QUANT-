"""Phase 336: define the in-flight request boundary during account deletion."""

import hashlib

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase336-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class DeletingExchange:
    def __init__(self, on_balance, **kwargs):
        self.on_balance = on_balance
        self.balance_calls = 0

    def get_balance(self):
        self.balance_calls += 1
        self.on_balance()
        return {"success": True, "observed": "request-already-started"}

    def close(self):
        pass


def test_delete_during_inflight_request_does_not_claim_to_cancel_that_request():
    repository = SQLiteDeltaAccountRepository()
    holder = {}
    clients = []

    def factory(**kwargs):
        client = DeletingExchange(
            lambda: holder["registry"].delete_account(
                tenant_id="tenant-phase336",
                account_id=holder["account_id"],
            ),
            **kwargs,
        )
        clients.append(client)
        return client

    registry = DeltaAccountRegistry(
        repository, TestOnlyProvider(), exchange_factory=factory
    )
    holder["registry"] = registry
    metadata = registry.register_account(
        tenant_id="tenant-phase336",
        label="inflight-boundary",
        region="INDIA",
        environment="SANDBOX",
        api_key="not-a-real-key",
        api_secret="not-a-real-secret",
    )
    holder["account_id"] = metadata.account_id
    session = registry.open_read_only_session(
        tenant_id="tenant-phase336", account_id=metadata.account_id
    )
    try:
        # The preflight check has passed when the fake exchange callback deletes
        # the record. This request was already dispatched and cannot be recalled.
        assert session.get_balance() == {
            "success": True,
            "observed": "request-already-started",
        }
        assert clients[0].balance_calls == 1
        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_balance()
        assert clients[0].balance_calls == 1
    finally:
        session.close()
        repository.close()
