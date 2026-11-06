"""Phase 316: bind settlement evidence to the exact normalized risk state."""

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
        tenant_id="tenant-state-hash", account_id="account-state-hash",
        provider_account_id="99126", region="INDIA", environment="SANDBOX",
    )


def _evidence(scope, state, *, state_hash=None):
    return AccountRiskReconciliationEvidence(
        scope=scope, reservation_id="QE-316", client_order_id="QE-316",
        source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-316",
        terminal_status="REJECTED", observed_at="2026-11-06T00:00:00+00:00",
        snapshot_hash="e" * 64,
        risk_state_hash=state_hash or hash_account_risk_state(state),
        identity_verified=True, orders_complete=True, fills_complete=True,
        positions_complete=True, open_order_absent=True,
    )


def _setup(path):
    repo = SQLiteAccountRiskRepository(str(path))
    coordinator = PersistentAccountRiskCoordinator(repo)
    scope = _scope()
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
        reservation_id="QE-316",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=250.0, leverage=1.0,
        ),
    )
    current = coordinator.get_state(scope)[1]
    state = replace(current, pending_orders=0, pending_exposure=0.0)
    return coordinator, repo, scope, state


def test_settlement_rejects_evidence_for_a_different_risk_state(tmp_path):
    coordinator, repo, scope, state = _setup(tmp_path / "wrong-state-hash.sqlite")
    changed = replace(state, current_exposure=999.0)
    evidence = _evidence(scope, changed)
    with pytest.raises(AccountRiskError, match="does not bind"):
        coordinator.settle_reservation(
            scope=scope, reservation_id="QE-316",
            expected_revision=state.revision, reconciled_state=state,
            evidence=evidence,
        )
    assert len(coordinator.list_pending_reservations(scope)) == 1
    assert coordinator.get_state(scope)[1].pending_exposure == 250.0
    repo.close()


def test_valid_state_hash_is_persisted_and_retrievable(tmp_path):
    coordinator, repo, scope, state = _setup(tmp_path / "valid-state-hash.sqlite")
    evidence = _evidence(scope, state)
    assert coordinator.settle_reservation(
        scope=scope, reservation_id="QE-316",
        expected_revision=state.revision, reconciled_state=state,
        evidence=evidence,
    )
    stored = coordinator.get_reservation_evidence(scope=scope, reservation_id="QE-316")
    assert stored == evidence
    assert stored.risk_state_hash == hash_account_risk_state(state)
    repo.close()


def test_risk_state_hash_is_deterministic_and_scope_bound():
    scope = _scope()
    state = AccountRiskState(
        scope=scope, risk_basis=10000.0, equity=10000.0, revision=7,
    )
    assert hash_account_risk_state(state) == hash_account_risk_state(state)
    other_scope = replace(scope, tenant_id="different-tenant")
    other_state = replace(state, scope=other_scope)
    assert hash_account_risk_state(state) != hash_account_risk_state(other_state)
