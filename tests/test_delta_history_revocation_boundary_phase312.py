"""Phase 312: revoke account snapshots during paginated history reads."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.accounts.delta_account_registry import (
    CredentialVaultError,
    DeltaReadOnlySession,
    EncryptedDeltaAccount,
)


class _HistoryPauseExchange:
    def __init__(self, paused_stage, entered, release):
        self.paused_stage = paused_stage
        self.entered = entered
        self.release = release
        self.calls = []
        self.closed = False

    def _get_authenticated_account_id(self):
        self.calls.append("identity")
        return "12345"

    def get_balance(self):
        self.calls.append("balance")
        return {"success": True, "result": []}

    def get_positions(self):
        self.calls.append("positions")
        return {"success": True, "result": []}

    def _history_result(self, stage):
        self.calls.append(stage)
        if self.paused_stage == stage:
            self.entered.set()
            if not self.release.wait(timeout=10):
                raise TimeoutError(f"test did not release {stage} read")
        if stage == "orders":
            return {
                "account_id": "12345",
                "complete": True,
                "orders": [],
                "snapshot_as_of_ns": 10,
                "pagination_evidence": {
                    "active_cursor_exhausted": True,
                    "history_cursor_exhausted": True,
                },
            }
        return {
            "account_id": "12345",
            "complete": True,
            "fills": [],
            "snapshot_as_of_ns": 11,
            "pagination_evidence": {"cursor_exhausted": True},
        }

    def get_order_history_snapshot(self, *, max_pages=100):
        return self._history_result("orders")

    def get_fill_history_snapshot(self, *, max_pages=100):
        return self._history_result("fills")

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    ("paused_stage", "expected_calls"),
    [
        ("orders", ["identity", "balance", "positions", "orders"]),
        ("fills", ["identity", "balance", "positions", "orders", "fills"]),
    ],
)
def test_subject_revocation_during_history_read_discards_snapshot(
    paused_stage, expected_calls
):
    entered, release = threading.Event(), threading.Event()
    authorized = {"value": True}
    exchange = _HistoryPauseExchange(paused_stage, entered, release)
    record = EncryptedDeltaAccount(
        account_id="internal-account",
        tenant_id="tenant-owner",
        venue="delta",
        region="INDIA",
        environment="SANDBOX",
        label="Owner Delta",
        provider_account_id="12345",
        key_id="test-key",
        algorithm="TEST-ONLY",
        ciphertext=b"test-only-ciphertext",
        created_at_ns=1,
        updated_at_ns=1,
    )
    session = DeltaReadOnlySession(
        exchange, record, lambda: authorized["value"] is True
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(session.get_account_snapshot)
            assert entered.wait(timeout=10), f"{paused_stage} read did not start"
            authorized["value"] = False
            release.set()
            with pytest.raises(CredentialVaultError, match="no longer authorized"):
                future.result(timeout=15)
        assert exchange.calls == expected_calls
    finally:
        release.set()
        session.close()
        assert exchange.closed
