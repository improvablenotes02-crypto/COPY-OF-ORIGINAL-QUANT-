"""Phase 312: durable pending risk reservation recovery."""

from core.accounts.account_risk import (
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import (
    hash_account_risk_state,
    AccountRiskReconciliationEvidence,
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
)


def _scope(tenant="tenant-recovery", account="account-recovery"):
    return AccountRiskScope(
        tenant_id=tenant, account_id=account,
        provider_account_id="99123", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def _register(coordinator, scope):
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )


def _evidence(scope, reservation_id, state):
    return AccountRiskReconciliationEvidence(
        scope=scope, reservation_id=reservation_id,
        client_order_id=reservation_id, source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-123",
        terminal_status="FILLED", observed_at="2026-11-06T00:00:00+00:00",
        snapshot_hash="a" * 64, risk_state_hash=hash_account_risk_state(state), identity_verified=True,
        orders_complete=True, fills_complete=True, positions_complete=True,
        open_order_absent=True,
    )


def _proposal(scope, notional=250.0):
    return OrderRiskProposal(
        scope=scope, risk_amount=25.0, notional=notional, leverage=1.0,
    )


def test_pending_reservations_survive_repository_restart(tmp_path):
    path = str(tmp_path / "pending-recovery.sqlite")
    scope = _scope()
    first_repo = SQLiteAccountRiskRepository(path)
    first = PersistentAccountRiskCoordinator(first_repo)
    _register(first, scope)
    decision, reservation = first.reserve_order(
        reservation_id="ambiguous-order-1", proposal=_proposal(scope),
    )
    assert decision.allowed
    assert reservation is not None and reservation.status == "PENDING"
    first_repo.close()

    second_repo = SQLiteAccountRiskRepository(path)
    second = PersistentAccountRiskCoordinator(second_repo)
    pending = second.list_pending_reservations(scope)
    assert len(pending) == 1
    assert pending[0].reservation_id == "ambiguous-order-1"
    assert pending[0].notional == 250.0
    assert pending[0].status == "PENDING"
    state = second.get_state(scope)[1]
    assert state.pending_orders == 1
    assert state.pending_exposure == 250.0
    second_repo.close()


def test_pending_reservation_recovery_is_account_scoped(tmp_path):
    repo = SQLiteAccountRiskRepository(str(tmp_path / "scoped-recovery.sqlite"))
    first_scope = _scope("tenant-a", "account-a")
    second_scope = _scope("tenant-b", "account-b")
    coordinator = PersistentAccountRiskCoordinator(repo)
    _register(coordinator, first_scope)
    _register(coordinator, second_scope)
    coordinator.reserve_order(
        reservation_id="tenant-a-order", proposal=_proposal(first_scope),
    )
    coordinator.reserve_order(
        reservation_id="tenant-b-order", proposal=_proposal(second_scope, 400.0),
    )
    assert [r.reservation_id for r in coordinator.list_pending_reservations(first_scope)] == ["tenant-a-order"]
    assert [r.reservation_id for r in coordinator.list_pending_reservations(second_scope)] == ["tenant-b-order"]
    repo.close()


def test_released_and_settled_reservations_are_not_recovered_as_pending(tmp_path):
    repo = SQLiteAccountRiskRepository(str(tmp_path / "terminal-recovery.sqlite"))
    scope = _scope()
    coordinator = PersistentAccountRiskCoordinator(repo)
    _register(coordinator, scope)
    coordinator.reserve_order(reservation_id="release-me", proposal=_proposal(scope))
    coordinator.reserve_order(reservation_id="settle-me", proposal=_proposal(scope, 300.0))
    assert coordinator.release_reservation(scope=scope, reservation_id="release-me")
    current = coordinator.get_state(scope)[1]
    reconciled = AccountRiskState(
        scope=scope, risk_basis=current.risk_basis, equity=current.equity,
        daily_pnl=current.daily_pnl, weekly_pnl=current.weekly_pnl,
        monthly_pnl=current.monthly_pnl, open_positions=1,
        pending_orders=0, current_exposure=300.0, pending_exposure=0.0,
        kill_switch=current.kill_switch, trading_enabled=current.trading_enabled,
        revision=current.revision,
    )
    assert coordinator.settle_reservation(
        scope=scope, reservation_id="settle-me",
        expected_revision=current.revision, reconciled_state=reconciled,
        evidence=_evidence(scope, "settle-me", reconciled),
    )
    assert coordinator.list_pending_reservations(scope) == ()
    repo.close()


def test_recovery_returns_empty_for_unregistered_account(tmp_path):
    repo = SQLiteAccountRiskRepository(str(tmp_path / "empty-recovery.sqlite"))
    assert PersistentAccountRiskCoordinator(repo).list_pending_reservations(_scope()) == ()
    repo.close()
