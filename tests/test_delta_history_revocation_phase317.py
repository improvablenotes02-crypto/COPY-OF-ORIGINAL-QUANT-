"""Phase 317: order and fill history reject revoked in-flight results."""
import threading
import pytest
from core.accounts.delta_account_registry import CredentialVaultError, DeltaReadOnlySession, EncryptedDeltaAccount

class BlockingHistory:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
    def _read(self, **kwargs):
        self.started.set()
        assert self.release.wait(2)
        return {"account_id": "12345", "complete": True, "orders": [], "fills": [], "pagination_evidence": {}}
    def get_order_history_snapshot(self, *, max_pages=100):
        return self._read(max_pages=max_pages)
    def get_fill_history_snapshot(self, *, max_pages=100):
        return self._read(max_pages=max_pages)

@pytest.mark.parametrize("method_name", ["get_order_history_snapshot", "get_fill_history_snapshot"])
def test_history_result_rejected_after_mid_request_revocation(method_name):
    exchange = BlockingHistory()
    authorization = {"allowed": True}
    record = EncryptedDeltaAccount(
        account_id="internal-account", tenant_id="tenant-owner", venue="delta",
        region="INDIA", environment="SANDBOX", label="Owner Delta",
        provider_account_id="12345", key_id="test-key", algorithm="TEST-ONLY",
        ciphertext=b"test-only-ciphertext", created_at_ns=1, updated_at_ns=1,
    )
    session = DeltaReadOnlySession(exchange, record, authorization_check=lambda: authorization["allowed"])
    results, errors = [], []
    def read():
        try:
            results.append(getattr(session, method_name)(max_pages=3))
        except Exception as exc:
            errors.append(exc)
    reader = threading.Thread(target=read)
    reader.start()
    assert exchange.started.wait(1)
    authorization["allowed"] = False
    exchange.release.set()
    reader.join(1)
    assert not reader.is_alive()
    assert results == []
    assert len(errors) == 1
    assert isinstance(errors[0], CredentialVaultError)
    assert "no longer authorized" in str(errors[0])
