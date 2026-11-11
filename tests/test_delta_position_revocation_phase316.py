"""Phase 316: positions must not escape after authorization revocation."""
import threading
from core.accounts.delta_account_registry import CredentialVaultError, DeltaReadOnlySession, EncryptedDeltaAccount

class BlockingPositions:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
    def get_positions(self):
        self.started.set()
        assert self.release.wait(2)
        return {"success": True, "result": [{"symbol": "TEST-PERP", "size": "1"}]}

def test_revocation_during_positions_request_blocks_result_release():
    exchange = BlockingPositions()
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
            results.append(session.get_positions())
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
