"""Phase 313: close the final authorization race at snapshot return."""
import pytest

from core.accounts.delta_account_registry import (
    CredentialVaultError,
    DeltaReadOnlySession,
    EncryptedDeltaAccount,
)


class _CompleteSnapshotExchange:
    def _get_authenticated_account_id(self):
        return "12345"

    def get_balance(self):
        return {"success": True, "result": []}

    def get_positions(self):
        return {"success": True, "result": []}

    def get_order_history_snapshot(self, *, max_pages=100):
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

    def get_fill_history_snapshot(self, *, max_pages=100):
        return {
            "account_id": "12345",
            "complete": True,
            "fills": [],
            "snapshot_as_of_ns": 11,
            "pagination_evidence": {"cursor_exhausted": True},
        }

    def close(self):
        self.closed = True


class _RevokedAtFinalIdentityCheckSession(DeltaReadOnlySession):
    def __init__(self, *args, authorization, **kwargs):
        super().__init__(*args, **kwargs)
        self.authorization = authorization
        self.identity_checks = 0

    def verify_provider_identity(self):
        result = super().verify_provider_identity()
        self.identity_checks += 1
        if self.identity_checks == 2:
            # Revoke immediately after the final venue identity check returns,
            # while get_account_snapshot is still assembling its return value.
            self.authorization["allowed"] = False
        return result


def test_snapshot_revalidates_authorization_at_actual_return_boundary():
    authorization = {"allowed": True}
    exchange = _CompleteSnapshotExchange()
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
    session = _RevokedAtFinalIdentityCheckSession(
        exchange, record, lambda: authorization["allowed"] is True,
        authorization=authorization,
    )
    try:
        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_account_snapshot()
        assert session.identity_checks == 2
    finally:
        session.close()
        assert exchange.closed
