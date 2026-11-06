"""Phase 321: settlement state, reservation, and evidence commit atomically."""
from dataclasses import replace
import sqlite3

import pytest

from core.accounts.account_risk import (
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
        tenant_id="tenant-phase321", account_id="account-phase321",
        provider_account_id="99141", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def _evidence(scope, state):
    return AccountRiskReconciliationEvidence(
        scope=scope, reservation_id="QE-phase321", client_order_id="QE-phase321",
        source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-phase321",
        terminal_status="REJECTED", observed_at="2026-11-06T00:00:00+00:00",
        snapshot_hash="b" * 64, risk_state_hash=hash_account_risk_state(state),
        identity_verified=True, orders_complete=True, fills_complete=True,
        positions_complete=True, open_order_absent=True,
    )


def test_evidence_write_failure_rolls_back_entire_settlement_and_allows_safe_retry(tmp_path):
    repository = SQLiteAccountRiskRepository(str(tmp_path / "settlement-atomic.sqlite"))
    coordinator = PersistentAccountRiskCoordinator(repository)
    scope = _scope()
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    decision, reservation = coordinator.reserve_order(
        reservation_id="QE-phase321",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=500.0, leverage=1.0,
        ),
    )
    assert decision.allowed
    assert reservation is not None
    before = coordinator.get_state(scope)[1]
    projected = replace(
        before, pending_orders=before.pending_orders - 1,
        pending_exposure=before.pending_exposure - 500.0,
    )
    evidence = _evidence(scope, projected)

    repository._connection.execute(
        """
        CREATE TRIGGER reject_phase321_evidence
        BEFORE INSERT ON account_risk_reservation_evidence
        BEGIN
            SELECT RAISE(ABORT, 'injected evidence persistence failure');
        END
        """
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected evidence persistence failure"):
        coordinator.settle_reservation(
            scope=scope, reservation_id="QE-phase321",
            expected_revision=before.revision, reconciled_state=projected,
            evidence=evidence,
        )

    assert coordinator.get_state(scope)[1] == before
    pending = coordinator.list_pending_reservations(scope)
    assert len(pending) == 1
    assert pending[0].status == "PENDING"
    assert coordinator.get_reservation_evidence(
        scope=scope, reservation_id="QE-phase321",
    ) is None

    repository._connection.execute("DROP TRIGGER reject_phase321_evidence")
    assert coordinator.settle_reservation(
        scope=scope, reservation_id="QE-phase321",
        expected_revision=before.revision, reconciled_state=projected,
        evidence=evidence,
    )
    settled = coordinator.get_state(scope)[1]
    assert settled.pending_orders == 0
    assert settled.pending_exposure == 0.0
    assert settled.revision == before.revision + 1
    assert coordinator.list_pending_reservations(scope) == ()
    assert coordinator.get_reservation_evidence(
        scope=scope, reservation_id="QE-phase321",
    ) == evidence
    repository.close()
