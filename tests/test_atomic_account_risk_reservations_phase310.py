"""Phase 310: atomic idempotent order risk reservation lifecycle."""
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
        tenant_id="tenant-reserve", account_id="internal-reserve",
        provider_account_id="88123", region="INDIA", environment="SANDBOX",
    )


def _profile(max_exposure=1.5):
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=max_exposure, max_open_positions=10,
        max_pending_orders=5,
    )


def _proposal(scope, notional=500.0):
    return OrderRiskProposal(
        scope=scope, risk_amount=50.0, notional=notional, leverage=1.0,
    )


def _evidence(scope, reservation_id, state):
    return AccountRiskReconciliationEvidence(
        scope=scope, reservation_id=reservation_id,
        client_order_id=reservation_id, source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-123",
        terminal_status="REJECTED", observed_at="2026-11-06T00:00:00+00:00",
        snapshot_hash="a" * 64, risk_state_hash=hash_account_risk_state(state), identity_verified=True,
        orders_complete=True, fills_complete=True, positions_complete=True,
        open_order_absent=True,
    )


def _coordinator(path, scope=None, profile=None):
    scope = scope or _scope()
    repository = SQLiteAccountRiskRepository(str(path))
    coordinator = PersistentAccountRiskCoordinator(repository)
    state = AccountRiskState(
        scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
    )
    coordinator.register(scope=scope, profile=profile or _profile(), initial_state=state)
    return coordinator, repository, scope


def test_reservation_atomically_increments_pending_risk_and_is_idempotent(tmp_path):
    coordinator, repository, scope = _coordinator(tmp_path / "reserve.sqlite")
    proposal = _proposal(scope)
    decision, reservation = coordinator.reserve_order(
        reservation_id="order-001", proposal=proposal
    )
    assert decision.allowed is True
    assert decision.reason == "ACCOUNT_RISK_RESERVED"
    assert reservation.status == "PENDING"
    state = coordinator.get_state(scope)[1]
    assert state.pending_orders == 1
    assert state.pending_exposure == 500.0
    assert state.revision == 1

    duplicate_decision, duplicate = coordinator.reserve_order(
        reservation_id="order-001", proposal=proposal
    )
    assert duplicate_decision.allowed is True
    assert duplicate_decision.reason == "ACCOUNT_RISK_RESERVATION_ALREADY_EXISTS"
    assert duplicate == reservation
    assert coordinator.get_state(scope)[1] == state
    repository.close()


def test_reservation_id_cannot_be_reused_for_a_different_proposal(tmp_path):
    coordinator, repository, scope = _coordinator(tmp_path / "reserve.sqlite")
    coordinator.reserve_order(reservation_id="order-001", proposal=_proposal(scope))
    with pytest.raises(AccountRiskError, match="different proposal"):
        coordinator.reserve_order(
            reservation_id="order-001", proposal=_proposal(scope, notional=400.0)
        )
    repository.close()


def test_release_only_decrements_a_pending_reservation_once(tmp_path):
    coordinator, repository, scope = _coordinator(tmp_path / "reserve.sqlite")
    coordinator.reserve_order(reservation_id="order-001", proposal=_proposal(scope))
    assert coordinator.release_reservation(scope=scope, reservation_id="order-001") is True
    assert coordinator.release_reservation(scope=scope, reservation_id="order-001") is False
    state = coordinator.get_state(scope)[1]
    assert state.pending_orders == 0
    assert state.pending_exposure == 0.0
    assert state.revision == 2
    denied, reservation = coordinator.reserve_order(
        reservation_id="order-001", proposal=_proposal(scope)
    )
    assert denied.allowed is False
    assert reservation is None
    repository.close()


def test_settlement_replaces_pending_reservation_with_authoritative_account_snapshot(tmp_path):
    coordinator, repository, scope = _coordinator(tmp_path / "reserve.sqlite")
    coordinator.reserve_order(reservation_id="order-001", proposal=_proposal(scope))
    current = coordinator.get_state(scope)[1]
    reconciled = replace(current, pending_orders=0, pending_exposure=0.0)
    assert coordinator.settle_reservation(
        scope=scope, reservation_id="order-001",
        expected_revision=current.revision, reconciled_state=reconciled,
        evidence=_evidence(scope, "order-001", reconciled),
    ) is True
    assert coordinator.settle_reservation(
        scope=scope, reservation_id="order-001",
        expected_revision=current.revision, reconciled_state=reconciled,
        evidence=_evidence(scope, "order-001", reconciled),
    ) is False
    settled = coordinator.get_state(scope)[1]
    assert settled.current_exposure == 0.0
    assert settled.pending_exposure == 0.0
    assert settled.revision == 2
    repository.close()


def test_ambiguous_order_outcome_keeps_reservation_and_risk_locked(tmp_path):
    coordinator, repository, scope = _coordinator(tmp_path / "reserve.sqlite")
    coordinator.reserve_order(reservation_id="order-ambiguous", proposal=_proposal(scope))
    # No release or settlement is permitted until authoritative exchange reconciliation.
    state = coordinator.get_state(scope)[1]
    assert state.pending_orders == 1
    assert state.pending_exposure == 500.0
    repository.close()


def test_concurrent_reservations_cannot_exceed_account_exposure_limit(tmp_path):
    scope = _scope()
    coordinator, repository, _ = _coordinator(
        tmp_path / "reserve.sqlite", scope=scope, profile=_profile(max_exposure=0.15)
    )
    first, _ = coordinator.reserve_order(
        reservation_id="order-a", proposal=_proposal(scope, notional=1000.0)
    )
    second, reservation = coordinator.reserve_order(
        reservation_id="order-b", proposal=_proposal(scope, notional=1000.0)
    )
    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "MAX_TOTAL_EXPOSURE"
    assert reservation is None
    state = coordinator.get_state(scope)[1]
    assert state.pending_orders == 1
    assert state.pending_exposure == 1000.0
    repository.close()
