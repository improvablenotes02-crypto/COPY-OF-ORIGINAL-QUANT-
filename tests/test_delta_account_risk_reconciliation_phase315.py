"""Phase 315: connect complete Delta read-only snapshots to risk settlement."""

from dataclasses import replace
import time

import pytest

from core.accounts.account_risk import (
    AccountRiskError,
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.delta_account_registry import (
    AccountScopeError,
    DeltaReadOnlySession,
    EncryptedDeltaAccount,
)
from core.accounts.delta_risk_reconciliation import reconcile_and_settle_pending_reservation
from core.accounts.persistent_account_risk import (
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
)


class _ReadOnlyDelta:
    def __init__(self, *, order_status="rejected", orders_complete=True):
        self.order_status = order_status
        self.orders_complete = orders_complete
        self.base = time.time_ns()

    def _get_authenticated_account_id(self):
        return "99125"

    def get_balance(self):
        return {"success": True, "result": [{"asset": "USD", "available_balance": "10000"}]}

    def get_positions(self):
        return {"success": True, "result": []}

    def get_order_history_snapshot(self, *, max_pages=100):
        return {
            "account_id": "99125", "complete": self.orders_complete,
            "orders": [{
                "id": 31501, "client_order_id": "QE-315",
                "product_id": 1, "size": "1", "status": self.order_status,
            }],
            "snapshot_as_of_ns": self.base - 500_000_000,
            "pagination_evidence": {
                "active_cursor_exhausted": True,
                "history_cursor_exhausted": True,
            },
        }

    def get_fill_history_snapshot(self, *, max_pages=100):
        return {
            "account_id": "99125", "complete": True, "fills": [],
            "snapshot_as_of_ns": self.base,
            "pagination_evidence": {"cursor_exhausted": True},
        }


class _Journal:
    def __init__(self):
        self.state = "DISPATCHING"
        self.evidence_sha256 = None

    def get(self, client_order_id):
        return {"client_order_id": client_order_id, "payload_sha256": "d" * 64}

    def transition(self, client_order_id, state, detail, *, evidence_sha256):
        self.state = state
        self.evidence_sha256 = evidence_sha256


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-315", account_id="internal-315",
        provider_account_id="99125", region="INDIA", environment="SANDBOX",
    )


def _session(scope, *, order_status="rejected", orders_complete=True):
    record = EncryptedDeltaAccount(
        account_id=scope.account_id, tenant_id=scope.tenant_id,
        venue="delta", region=scope.region, environment=scope.environment,
        label="test", provider_account_id=scope.provider_account_id,
        key_id="test", algorithm="test", ciphertext=b"x",
        created_at_ns=1, updated_at_ns=1,
    )
    return DeltaReadOnlySession(
        _ReadOnlyDelta(order_status=order_status, orders_complete=orders_complete),
        record,
    )


def _setup(tmp_path, *, order_status="rejected", orders_complete=True):
    scope = _scope()
    repo = SQLiteAccountRiskRepository(str(tmp_path / "risk-315.sqlite"))
    coordinator = PersistentAccountRiskCoordinator(repo)
    profile = AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )
    coordinator.register(
        scope=scope, profile=profile,
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    coordinator.reserve_order(
        reservation_id="QE-315",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=250.0, leverage=1.0,
        ),
    )
    current = coordinator.get_state(scope)[1]
    reconciled = replace(current, pending_orders=0, pending_exposure=0.0)
    return coordinator, repo, scope, _session(
        scope, order_status=order_status, orders_complete=orders_complete,
    ), reconciled


def test_terminal_delta_rejection_settles_and_persists_snapshot_evidence(tmp_path):
    coordinator, repo, scope, session, reconciled = _setup(tmp_path)
    journal = _Journal()
    result = reconcile_and_settle_pending_reservation(
        coordinator=coordinator, journal=journal, scope=scope,
        reservation_id="QE-315", session=session,
        reconciled_state=reconciled, now_ns=time.time_ns() + 2_000_000_000,
    )
    assert result["settled"] is True
    assert result["terminal_status"] == "REJECTED"
    assert journal.state == "REJECTED"
    assert coordinator.list_pending_reservations(scope) == ()
    evidence = coordinator.get_reservation_evidence(
        scope=scope, reservation_id="QE-315",
    )
    assert evidence is not None
    assert evidence.client_order_id == "QE-315"
    assert evidence.exchange_order_id == "31501"
    repo.close()


def test_open_order_remains_pending_even_when_history_is_complete(tmp_path):
    coordinator, repo, scope, session, reconciled = _setup(
        tmp_path, order_status="open",
    )
    result = reconcile_and_settle_pending_reservation(
        coordinator=coordinator, journal=_Journal(), scope=scope,
        reservation_id="QE-315", session=session,
        reconciled_state=reconciled, now_ns=time.time_ns() + 2_000_000_000,
    )
    assert result["settled"] is False
    assert "non-terminal" in result["reason"]
    assert len(coordinator.list_pending_reservations(scope)) == 1
    repo.close()


def test_incomplete_delta_snapshot_cannot_settle_reservation(tmp_path):
    coordinator, repo, scope, session, reconciled = _setup(
        tmp_path, orders_complete=False,
    )
    with pytest.raises(AccountScopeError):
        reconcile_and_settle_pending_reservation(
            coordinator=coordinator, journal=_Journal(), scope=scope,
            reservation_id="QE-315", session=session,
            reconciled_state=reconciled, now_ns=time.time_ns() + 2_000_000_000,
        )
    assert len(coordinator.list_pending_reservations(scope)) == 1
    repo.close()


def test_settlement_cannot_release_other_pending_order_capacity(tmp_path):
    coordinator, repo, scope, session, reconciled = _setup(tmp_path)
    coordinator.reserve_order(
        reservation_id="QE-315-OTHER",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=100.0, leverage=1.0,
        ),
    )
    current = coordinator.get_state(scope)[1]
    bad_reconciled = replace(current, pending_orders=0, pending_exposure=0.0)
    with pytest.raises(AccountRiskError, match="other pending orders"):
        reconcile_and_settle_pending_reservation(
            coordinator=coordinator, journal=_Journal(), scope=scope,
            reservation_id="QE-315", session=session,
            reconciled_state=bad_reconciled, now_ns=time.time_ns() + 2_000_000_000,
        )
    assert len(coordinator.list_pending_reservations(scope)) == 2
    repo.close()


def test_session_scope_mismatch_fails_before_exchange_observation(tmp_path):
    coordinator, repo, scope, session, reconciled = _setup(tmp_path)
    other = replace(scope, tenant_id="other-tenant")
    with pytest.raises(AccountRiskError, match="session"):
        reconcile_and_settle_pending_reservation(
            coordinator=coordinator, journal=_Journal(), scope=other,
            reservation_id="QE-315", session=session,
            reconciled_state=replace(reconciled, scope=other),
        )
    assert len(coordinator.list_pending_reservations(scope)) == 1
    repo.close()


def test_filled_order_stays_pending_without_terminalizing_submission_journal(tmp_path):
    coordinator, repo, scope, session, reconciled = _setup(
        tmp_path, order_status="filled",
    )
    journal = _Journal()
    result = reconcile_and_settle_pending_reservation(
        coordinator=coordinator, journal=journal, scope=scope,
        reservation_id="QE-315", session=session,
        reconciled_state=reconciled, now_ns=time.time_ns() + 2_000_000_000,
    )
    assert result["settled"] is False
    assert "position state" in result["reason"]
    assert journal.state == "DISPATCHING"
    assert len(coordinator.list_pending_reservations(scope)) == 1
    state = coordinator.get_state(scope)[1]
    assert state.pending_orders == 1
    assert state.pending_exposure == 250.0
    repo.close()
