"""Phase 333: read-only Delta sessions close deterministically and fail closed."""

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
        tenant_id="tenant-phase333",
        label="session-lifecycle",
        region="INDIA",
        environment="SANDBOX",
        api_key="test-key",
        api_secret="test-secret",
    )
    session = registry.open_read_only_session(
        tenant_id="tenant-phase333", account_id=metadata.account_id
    )
    return repository, session, exchanges[0]


def test_close_is_idempotent_and_prevents_further_exchange_calls():
    repository, session, exchange = _make_session()
    try:
        assert session.closed is False
        session.close()
        session.close()
        assert session.closed is True
        assert exchange.close_calls == 1
        with pytest.raises(CredentialVaultError, match="session is closed"):
            session.get_balance()
        assert exchange.balance_calls == 0
    finally:
        repository.close()


def test_context_manager_closes_session_even_when_body_raises():
    repository, session, exchange = _make_session()
    try:
        with pytest.raises(RuntimeError, match="sentinel"):
            with session as active:
                assert active is session
                raise RuntimeError("sentinel")
        assert session.closed is True
        assert exchange.close_calls == 1
        with pytest.raises(CredentialVaultError, match="session is closed"):
            session.get_positions()
    finally:
        repository.close()


def test_session_close_swallows_client_cleanup_error_but_stays_closed():
    repository, session, exchange = _make_session()

    def fail_close():
        exchange.close_calls += 1
        raise RuntimeError("cleanup detail must not escape")

    exchange.close = fail_close
    try:
        session.close()
        assert session.closed is True
        assert exchange.close_calls == 1
        with pytest.raises(CredentialVaultError, match="session is closed"):
            session.get_balance()
    finally:
        repository.close()
