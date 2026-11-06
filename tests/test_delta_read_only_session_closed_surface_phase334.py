"""Phase 334: every read-only session entry point refuses use after close."""

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
        return CiphertextEnvelope("test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class FakeExchange:
    def __init__(self, **kwargs):
        self.close_calls = 0
        self.balance_calls = 0

    def close(self):
        self.close_calls += 1

    def get_balance(self):
        self.balance_calls += 1
        return {"success": True}


def _make_session():
    repository = SQLiteDeltaAccountRepository()
    exchanges = []

    def factory(**kwargs):
        exchange = FakeExchange(**kwargs)
        exchanges.append(exchange)
        return exchange

    registry = DeltaAccountRegistry(
        repository, TestOnlyProvider(), exchange_factory=factory
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase334",
        label="closed-surface",
        region="INDIA",
        environment="SANDBOX",
        api_key="test-key",
        api_secret="test-secret",
    )
    session = registry.open_read_only_session(
        tenant_id="tenant-phase334", account_id=metadata.account_id
    )
    return repository, session, exchanges[0]


@pytest.mark.parametrize(
    "operation",
    [
        lambda session: session.verify_provider_identity(),
        lambda session: session.get_balance(),
        lambda session: session.get_positions(),
        lambda session: session.get_order_history_snapshot(),
        lambda session: session.get_fill_history_snapshot(),
        lambda session: session.get_account_snapshot(),
    ],
    ids=[
        "provider-identity",
        "balance",
        "positions",
        "order-history",
        "fill-history",
        "account-snapshot",
    ],
)
def test_every_public_read_entry_point_fails_after_close(operation):
    repository, session, exchange = _make_session()
    try:
        session.close()
        with pytest.raises(CredentialVaultError, match="session is closed"):
            operation(session)
        assert exchange.close_calls == 1
        assert exchange.balance_calls == 0
    finally:
        repository.close()
