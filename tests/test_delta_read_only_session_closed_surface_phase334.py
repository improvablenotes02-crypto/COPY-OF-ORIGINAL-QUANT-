"""Phase 334: every read-only session entry point refuses use after close."""

import pytest

from tests.test_delta_read_only_session_lifecycle_phase333 import _make_session
from core.accounts.delta_account_registry import CredentialVaultError


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
