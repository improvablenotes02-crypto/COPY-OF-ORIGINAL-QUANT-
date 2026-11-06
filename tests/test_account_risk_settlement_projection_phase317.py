"""Phase 317: fail-closed account-risk settlement state projection."""

from dataclasses import replace

import pytest

from core.accounts.account_risk import (
    AccountRiskError,
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import (
    AccountRiskReconciliationEvidence,
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
    hash_account_risk_state,
)


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-317", account_id="account-317",
        provider_account_id="99127", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def _setup(path):
    repo = SQLiteAccountRiskRepository(str(path))
    coordinator = PersistentAccountRiskCoordinator(repo)
    scope = _scope()
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    coordinator.reserve_order(
        reservation_id="QE-317",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=250.0, leverage=1.0,
        ),
    )
    current = coordinator.get_state(scope)[1]
    projected = replace(current, pending_orders=0, pending_exposure=0.0)
    return coordinator, repo, scope, current, projected


def _evidence(scope, state, *, terminal_status="REJECTED"):
    return AccountRiskReconciliationEvidence(
        scope=scope, reservation_id="QE-317", client_order_id="QE-317",
        source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-317",
        terminal_status=terminal_status, observed_at="2026-11-06T00:00:00+00:00",
        snapshot_hash="f" * 64, risk_state_hash=hash_account_risk_state(state),
        identity_verified=True, orders_complete=True, fills_complete=True,
        positions_complete=True, open_order_absent=True,
    )


def test_executed_order_cannot_settle_without_position_reconciliation(tmp_path):
    coordinator, repo, scope, current, projected = _setup(
        tmp_path / "filled-order-hold.sqlite",
    )
    evidence = _evidence(scope, projected, terminal_status="FILLED")
    with pytest.raises(AccountRiskError, match="position reconciliation"):
        coordinator.settle_reservation(
            scope=scope, reservation_id="QE-317",
            expected_revision=current.revision, reconciled_state=projected,
            evidence=evidence,
        )
    assert len(coordinator.list_pending_reservations(scope)) == 1
    assert coordinator.get_state(scope)[1] == current
    repo.close()


def test_rejected_order_cannot_smuggle_unverified_risk_state_changes(tmp_path):
    coordinator, repo, scope, current, projected = _setup(
        tmp_path / "mutated-state-hold.sqlite",
    )
    forged = replace(
        projected, equity=projected.equity * 10,
        daily_pnl=0.0, current_exposure=0.0,
        kill_switch=False, trading_enabled=True,
    )
    evidence = _evidence(scope, forged)
    with pytest.raises(AccountRiskError, match="all other risk fields must remain unchanged"):
        coordinator.settle_reservation(
            scope=scope, reservation_id="QE-317",
            expected_revision=current.revision, reconciled_state=forged,
            evidence=evidence,
        )
    assert len(coordinator.list_pending_reservations(scope)) == 1
    assert coordinator.get_state(scope)[1] == current
    repo.close()


def test_rejected_order_releases_only_its_own_pending_reservation(tmp_path):
    coordinator, repo, scope, current, projected = _setup(
        tmp_path / "single-reservation-release.sqlite",
    )
    coordinator.reserve_order(
        reservation_id="QE-317-OTHER",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=10.0, notional=100.0, leverage=1.0,
        ),
    )
    current = coordinator.get_state(scope)[1]
    projected = replace(current, pending_orders=1, pending_exposure=100.0)
    evidence = _evidence(scope, projected)
    assert coordinator.settle_reservation(
        scope=scope, reservation_id="QE-317",
        expected_revision=current.revision, reconciled_state=projected,
        evidence=evidence,
    )
    assert [item.reservation_id for item in coordinator.list_pending_reservations(scope)] == [
        "QE-317-OTHER"
    ]
    settled = coordinator.get_state(scope)[1]
    assert settled.pending_orders == 1
    assert settled.pending_exposure == 100.0
    assert settled.current_exposure == current.current_exposure
    assert settled.equity == current.equity
    repo.close()
