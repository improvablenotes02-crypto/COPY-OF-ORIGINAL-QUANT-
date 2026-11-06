"""Phase 326: settlement evidence is visible only within its exact account scope."""
from dataclasses import replace

import pytest

from core.accounts.account_risk import (
    AccountRiskError, AccountRiskProfile, AccountRiskScope, AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import (
    AccountRiskReconciliationEvidence, SQLiteAccountRiskRepository,
    hash_account_risk_state,
)


def _scope(account, provider):
    return AccountRiskScope(
        tenant_id="tenant-phase326", account_id=account,
        provider_account_id=provider, region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_reconciliation_evidence_cannot_be_read_or_applied_from_another_account(tmp_path):
    repository = SQLiteAccountRiskRepository(str(tmp_path / "evidence-scope.sqlite"))
    scope_a, scope_b = _scope("account-a", "99601"), _scope("account-b", "99602")
    reservation_id = "QE-phase326-account-a"
    try:
        for scope in (scope_a, scope_b):
            repository.register(
                scope=scope, profile=_profile(),
                initial_state=AccountRiskState(
                    scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
                ),
            )
        decision, reservation = repository.reserve_order(
            reservation_id=reservation_id,
            proposal=OrderRiskProposal(
                scope=scope_a, risk_amount=25.0, notional=500.0, leverage=1.0,
            ),
        )
        assert decision.allowed and reservation is not None
        _, current = repository.get(scope_a)
        projected = replace(
            current, pending_orders=0, pending_exposure=0.0,
            revision=current.revision + 1,
        )
        evidence = AccountRiskReconciliationEvidence(
            scope=scope_a, reservation_id=reservation_id,
            client_order_id=reservation_id, source="DELTA_AUTHENTICATED_READ",
            exchange_order_id="delta-phase326-a", terminal_status="REJECTED",
            observed_at="2026-11-06T00:00:00+00:00",
            snapshot_hash="e" * 64,
            risk_state_hash=hash_account_risk_state(projected),
            identity_verified=True, orders_complete=True, fills_complete=True,
            positions_complete=True, open_order_absent=True,
        )
        assert repository.settle_reservation(
            scope=scope_a, reservation_id=reservation_id,
            expected_revision=current.revision, reconciled_state=projected,
            evidence=evidence,
        ) is True

        assert repository.get_reservation_evidence(
            scope=scope_a, reservation_id=reservation_id,
        ) == evidence
        with pytest.raises(AccountRiskError, match="scope mismatch"):
            repository.get_reservation_evidence(
                scope=scope_b, reservation_id=reservation_id,
            )
        with pytest.raises(AccountRiskError, match="evidence does not match"):
            repository.settle_reservation(
                scope=scope_b, reservation_id=reservation_id,
                expected_revision=0, reconciled_state=AccountRiskState(
                    scope=scope_b, risk_basis=10000.0, equity=10000.0,
                    revision=0,
                ),
                evidence=evidence,
            )
        _, untouched = repository.get(scope_b)
        assert untouched.pending_orders == 0
        assert untouched.pending_exposure == 0.0
        assert untouched.revision == 0
    finally:
        repository.close()
