"""Phase 313: validate risk-state invariants at persistence boundaries."""

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
    hash_account_risk_state,
    AccountRiskReconciliationEvidence,
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
)


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-invariants", account_id="account-invariants",
        provider_account_id="99124", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def _state(scope, **changes):
    values = dict(scope=scope, risk_basis=10000.0, equity=10000.0, revision=0)
    values.update(changes)
    return AccountRiskState(**values)


def _evidence(scope, reservation_id, state):
    return AccountRiskReconciliationEvidence(
        scope=scope, reservation_id=reservation_id,
        client_order_id=reservation_id, source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-313",
        terminal_status="FILLED", observed_at="2026-11-06T00:00:00+00:00",
        snapshot_hash="c" * 64, risk_state_hash=hash_account_risk_state(state), identity_verified=True,
        orders_complete=True, fills_complete=True, positions_complete=True,
        open_order_absent=True,
    )


def _coordinator(path):
    repo = SQLiteAccountRiskRepository(str(path))
    coordinator = PersistentAccountRiskCoordinator(repo)
    scope = _scope()
    coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope))
    return coordinator, repo, scope


@pytest.mark.parametrize(
    "changes",
    [
        {"risk_basis": 0.0},
        {"equity": -1.0},
        {"equity": float("nan")},
        {"daily_pnl": float("inf")},
        {"current_exposure": -0.01},
        {"pending_exposure": float("nan")},
        {"open_positions": -1},
        {"pending_orders": True},
        {"kill_switch": 1},
    ],
)
def test_register_rejects_invalid_risk_state_before_commit(tmp_path, changes):
    repo = SQLiteAccountRiskRepository(str(tmp_path / "register-invalid.sqlite"))
    scope = _scope()
    coordinator = PersistentAccountRiskCoordinator(repo)
    with pytest.raises(AccountRiskError):
        coordinator.register(
            scope=scope, profile=_profile(),
            initial_state=_state(scope, **changes),
        )
    assert coordinator.get_state(scope) is None
    repo.close()


def test_compare_and_swap_rejects_invalid_state_without_mutation(tmp_path):
    coordinator, repo, scope = _coordinator(tmp_path / "cas-invalid.sqlite")
    invalid = _state(scope, pending_exposure=-10.0)
    with pytest.raises(AccountRiskError, match="pending_exposure"):
        coordinator.update_state(scope=scope, expected_revision=0, state=invalid)
    persisted = coordinator.get_state(scope)[1]
    assert persisted.revision == 0
    assert persisted.pending_exposure == 0.0
    repo.close()


def test_settlement_rejects_invalid_reconciled_state_and_keeps_reservation_pending(tmp_path):
    coordinator, repo, scope = _coordinator(tmp_path / "settle-invalid.sqlite")
    proposal = OrderRiskProposal(
        scope=scope, risk_amount=25.0, notional=250.0, leverage=1.0,
    )
    coordinator.reserve_order(reservation_id="invalid-settlement", proposal=proposal)
    current = coordinator.get_state(scope)[1]
    invalid = replace(current, current_exposure=-1.0)
    with pytest.raises(AccountRiskError, match="current_exposure"):
        coordinator.settle_reservation(
            scope=scope, reservation_id="invalid-settlement",
            expected_revision=current.revision, reconciled_state=invalid,
            evidence=_evidence(scope, "invalid-settlement", invalid),
        )
    assert len(coordinator.list_pending_reservations(scope)) == 1
    assert coordinator.get_state(scope)[1].pending_exposure == 250.0
    repo.close()


def test_valid_revisioned_state_remains_persistable(tmp_path):
    coordinator, repo, scope = _coordinator(tmp_path / "valid-state.sqlite")
    current = coordinator.get_state(scope)[1]
    updated = replace(current, daily_pnl=-25.0)
    saved = coordinator.update_state(scope=scope, expected_revision=0, state=updated)
    assert saved.revision == 1
    assert coordinator.get_state(scope)[1].daily_pnl == -25.0
    repo.close()
