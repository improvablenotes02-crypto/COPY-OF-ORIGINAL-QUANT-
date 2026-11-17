"""Phase 314: serialize Delta session close against in-flight reads."""
import threading

from core.accounts.delta_account_registry import (
    DeltaReadOnlySession,
    EncryptedDeltaAccount,
)


class _BlockingBalanceExchange:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def get_balance(self):
        self.started.set()
        assert self.release.wait(2), "test did not release the blocked exchange call"
        return {"success": True, "result": []}

    def close(self):
        self.closed = True


def _record():
    return EncryptedDeltaAccount(
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


def test_close_waits_for_inflight_read_then_closes_client():
    exchange = _BlockingBalanceExchange()
    session = DeltaReadOnlySession(exchange, _record())
    read_result = []
    read_errors = []
    close_started = threading.Event()
    close_finished = threading.Event()

    def read():
        try:
            read_result.append(session.get_balance())
        except Exception as exc:  # pragma: no cover - assertion reports thread error
            read_errors.append(exc)

    def close():
        close_started.set()
        session.close()
        close_finished.set()

    reader = threading.Thread(target=read)
    reader.start()
    assert exchange.started.wait(1)

    closer = threading.Thread(target=close)
    closer.start()
    assert close_started.wait(1)
    # The in-flight operation owns the session lock; close cannot tear down
    # the exchange client until the operation has completed.
    assert not close_finished.wait(0.05)
    assert exchange.closed is False

    exchange.release.set()
    reader.join(1)
    closer.join(1)

    assert not reader.is_alive()
    assert not closer.is_alive()
    assert read_errors == []
    assert read_result == [{"success": True, "result": []}]
    assert exchange.closed is True
    assert session.closed is True
