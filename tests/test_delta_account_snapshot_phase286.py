"""Phase 286: complete read-only Delta account snapshot contract."""
import hashlib

import pytest

from core.accounts.delta_account_registry import (
    AccountScopeError,
    CiphertextEnvelope,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class TestOnlyEncryptionProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("test-only", "TEST-ONLY-XOR", tag + bytes(x ^ 0xA5 for x in plaintext))

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(x ^ 0xA5 for x in envelope.ciphertext[16:])


class FakeDeltaExchange:
    def __init__(self, *, api_key, api_secret, base_url, state):
        self.state = state
        self.base_url = base_url

    def _get_authenticated_account_id(self):
        sequence = self.state["identity_sequence"]
        if sequence:
            return sequence.pop(0)
        return self.state["identity"]

    def get_balance(self):
        return {"success": self.state.get("balance_success", True), "result": [{"asset": "USD"}]}

    def get_positions(self):
        return {"success": self.state.get("positions_success", True), "result": []}

    def get_order_history_snapshot(self, *, max_pages=100):
        return {
            "account_id": self.state.get("orders_account_id", "123"),
            "complete": self.state.get("orders_complete", True),
            "orders": [],
            "snapshot_as_of_ns": 101,
            "pagination_evidence": {
                "active_cursor_exhausted": self.state.get("active_cursor_exhausted", True),
                "history_cursor_exhausted": self.state.get("history_cursor_exhausted", True),
            },
        }

    def get_fill_history_snapshot(self, *, max_pages=100):
        return {
            "account_id": self.state.get("fills_account_id", "123"),
            "complete": self.state.get("fills_complete", True),
            "fills": [],
            "snapshot_as_of_ns": 102,
            "pagination_evidence": {
                "cursor_exhausted": self.state.get("fill_cursor_exhausted", True),
            },
        }


def _setup(**overrides):
    state = {
        "identity": "123",
        "identity_sequence": ["123", "123", "123"],
    }
    state.update(overrides)
    repository = SQLiteDeltaAccountRepository()
    registry = DeltaAccountRegistry(
        repository,
        TestOnlyEncryptionProvider(),
        exchange_factory=lambda **kwargs: FakeDeltaExchange(**kwargs, state=state),
    )
    metadata = registry.register_account(
        tenant_id="tenant-a",
        label="primary",
        region="INDIA",
        environment="SANDBOX",
        api_key="local-key",
        api_secret="local-secret",
    )
    bound = registry.verify_and_bind_identity(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    assert bound.provider_account_id == "123"
    return registry, repository, metadata, state


def test_account_snapshot_collects_all_components_under_bound_identity():
    registry, repository, metadata, state = _setup()
    session = registry.open_read_only_session(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    snapshot = session.get_account_snapshot()
    assert snapshot["venue"] == "delta"
    assert snapshot["tenant_id"] == "tenant-a"
    assert snapshot["internal_account_id"] == metadata.account_id
    assert snapshot["provider_account_id"] == "123"
    assert snapshot["region"] == "INDIA"
    assert snapshot["environment"] == "SANDBOX"
    assert snapshot["balances"]["success"] is True
    assert snapshot["positions"]["success"] is True
    assert snapshot["orders"] == []
    assert snapshot["fills"] == []
    assert snapshot["completeness"] == {
        "balances": True,
        "positions": True,
        "orders": True,
        "fills": True,
        "order_cursor_exhausted": True,
        "fill_cursor_exhausted": True,
    }
    assert snapshot["component_observed_at_ns"] == {"orders": 101, "fills": 102}
    assert snapshot["observation_is_exchange_atomic"] is False
    assert not hasattr(session, "place_order")
    assert not hasattr(session, "cancel_order")
    repository.close()


def test_snapshot_refuses_unbound_provider_identity():
    repository = SQLiteDeltaAccountRepository()
    state = {"identity": "123", "identity_sequence": []}
    registry = DeltaAccountRegistry(
        repository,
        TestOnlyEncryptionProvider(),
        exchange_factory=lambda **kwargs: FakeDeltaExchange(**kwargs, state=state),
    )
    metadata = registry.register_account(
        tenant_id="tenant-a", label="unbound", region="INDIA",
        environment="SANDBOX", api_key="k", api_secret="s",
    )
    session = registry.open_read_only_session(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    with pytest.raises(AccountScopeError, match="must be verified and bound"):
        session.get_account_snapshot()
    repository.close()


@pytest.mark.parametrize(
    "override",
    [
        {"balance_success": False},
        {"positions_success": False},
        {"orders_complete": False},
        {"fills_complete": False},
        {"active_cursor_exhausted": False},
        {"history_cursor_exhausted": False},
        {"fill_cursor_exhausted": False},
        {"orders_account_id": "999"},
        {"fills_account_id": "999"},
    ],
)
def test_incomplete_or_wrong_scope_component_refuses_whole_snapshot(override):
    registry, repository, metadata, state = _setup(**override)
    session = registry.open_read_only_session(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    with pytest.raises(AccountScopeError):
        session.get_account_snapshot()
    repository.close()


def test_identity_change_during_collection_refuses_snapshot():
    registry, repository, metadata, state = _setup(
        identity_sequence=["123", "123", "456"]
    )
    session = registry.open_read_only_session(
        tenant_id="tenant-a", account_id=metadata.account_id
    )
    with pytest.raises(AccountScopeError, match="does not match"):
        session.get_account_snapshot()
    repository.close()
