"""Phase 315: do not release venue data after mid-request authorization revocation."""
import threading

from core.accounts.delta_account_registry import (
    CredentialVaultError,
    DeltaReadOnlySession,
    EncryptedDeltaAccount,
)


class _BlockingBalanceExchange:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def get_balance(self):
        self.started.set()
        assert self.release.wait(2), "test did not release the blocked exchange call"
        return {"success": True, "result": [{"asset": "TEST", "available": "10"}]}


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


def test_revocation_during_balance_request_blocks_result_release():
    exchange = _BlockingBalanceExchange()
    authorization = {"allowed": True}
    session = DeltaReadOnlySession(
        exchange,
        _record(),
        authorization_check=lambda: authorization["allowed"],
    )
    results = []
    errors = []

    def read_balance():
        try:
            results.append(session.get_balance())
        except Exception as exc:  # captured for assertion in the parent thread
            errors.append(exc)

    reader = threading.Thread(target=read_balance)
    reader.start()
    assert exchange.started.wait(1)

    # Revoke while the provider call is blocked, then let the provider return.
    authorization["allowed"] = False
    exchange.release.set()
    reader.join(1)

    assert not reader.is_alive()
    assert results == []
    assert len(errors) == 1
    assert isinstance(errors[0], CredentialVaultError)
    assert "no longer authorized" in str(errors[0])
