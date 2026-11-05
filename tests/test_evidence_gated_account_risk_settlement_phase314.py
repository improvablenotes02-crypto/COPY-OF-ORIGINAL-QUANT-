"""Phase 314: evidence-gated, durable risk reservation settlement."""

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
        tenant_id="tenant-evidence", account_id="account-evidence",
        provider_account_id="99125", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def _evidence(scope, reservation_id, state_hash=None, **changes):
    values = dict(
        scope=scope, reservation_id=reservation_id,
        client_order_id=reservation_id, source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-314",
        terminal_status="FILLED", observed_at="2026-11-06T00:00:00+00:00",
        snapshot_hash="b" * 64, risk_state_hash=state_hash or ("c" * 64), identity_verified=True,
        orders_complete=True, fills_complete=True, positions_complete=True,
        open_order_absent=True,
    )
    values.update(changes)
    return AccountRiskReconciliationEvidence(**values)


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
        reservation_id="settle-evidence-314",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=250.0, leverage=1.0,
        ),
    )
    return coordinator, repo, scope


def _reconciled_state(coordinator, scope):
    current = coordinator.get_state(scope)[1]
    return replace(
        current, pending_orders=0, pending_exposure=0.0,
        current_exposure=250.0, open_positions=1,
    )


def test_settlement_requires_complete_authenticated_terminal_evidence(tmp_path):
    coordinator, repo, scope = _setup(tmp_path / "evidence-required.sqlite")
    state = _reconciled_state(coordinator, scope)
    evidence = _evidence(scope, "settle-evidence-314", hash_account_risk_state(state))
    assert coordinator.settle_reservation(
        scope=scope, reservation_id=evidence.reservation_id,
        expected_revision=state.revision, reconciled_state=state,
        evidence=evidence,
    )
    assert coordinator.list_pending_reservations(scope) == ()
    repo.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "UNVERIFIED"},
        {"client_order_id": "different-client-order"},
        {"identity_verified": False},
        {"orders_complete": False},
        {"fills_complete": False},
        {"positions_complete": False},
        {"open_order_absent": False},
        {"terminal_status": "OPEN"},
        {"snapshot_hash": "not-a-hash"},
        {"observed_at": "2026-11-06T00:00:00"},
    ],
)
def test_incomplete_or_untrusted_evidence_is_rejected(tmp_path, changes):
    scope = _scope()
    with pytest.raises(AccountRiskError):
        _evidence(scope, "reservation-314", **changes)


def test_evidence_must_bind_to_exact_reservation_and_scope(tmp_path):
    coordinator, repo, scope = _setup(tmp_path / "evidence-binding.sqlite")
    state = _reconciled_state(coordinator, scope)
    wrong_id = _evidence(scope, "different-reservation", hash_account_risk_state(state))
    with pytest.raises(AccountRiskError, match="does not match"):
        coordinator.settle_reservation(
            scope=scope, reservation_id="settle-evidence-314",
            expected_revision=state.revision, reconciled_state=state,
            evidence=wrong_id,
        )
    assert len(coordinator.list_pending_reservations(scope)) == 1
    repo.close()


def test_settlement_evidence_survives_repository_restart(tmp_path):
    path = str(tmp_path / "evidence-durable.sqlite")
    coordinator, first_repo, scope = _setup(path)
    state = _reconciled_state(coordinator, scope)
    evidence = _evidence(scope, "settle-evidence-314", hash_account_risk_state(state))
    assert coordinator.settle_reservation(
        scope=scope, reservation_id=evidence.reservation_id,
        expected_revision=state.revision, reconciled_state=state,
        evidence=evidence,
    )
    first_repo.close()

    second_repo = SQLiteAccountRiskRepository(path)
    second = PersistentAccountRiskCoordinator(second_repo)
    stored = second.get_reservation_evidence(
        scope=scope, reservation_id="settle-evidence-314",
    )
    assert stored == evidence
    assert second.list_pending_reservations(scope) == ()
    second_repo.close()


def test_evidence_lookup_rejects_cross_account_scope(tmp_path):
    coordinator, repo, scope = _setup(tmp_path / "evidence-scope.sqlite")
    state = _reconciled_state(coordinator, scope)
    evidence = _evidence(scope, "settle-evidence-314")
    coordinator.settle_reservation(
        scope=scope, reservation_id=evidence.reservation_id,
        expected_revision=state.revision, reconciled_state=state,
        evidence=evidence,
    )
    other_scope = replace(scope, tenant_id="another-tenant")
    with pytest.raises(AccountRiskError, match="scope mismatch"):
        coordinator.get_reservation_evidence(
            scope=other_scope, reservation_id="settle-evidence-314",
        )
    repo.close()
