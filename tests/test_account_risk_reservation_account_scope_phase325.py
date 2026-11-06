"""Phase 325: reservation lifecycle operations cannot cross account boundaries."""
import pytest

from core.accounts.account_risk import (
    AccountRiskError, AccountRiskProfile, AccountRiskScope, AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository


def _scope(account, provider):
    return AccountRiskScope(
        tenant_id="tenant-phase325", account_id=account,
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


def _reserve(repository, scope, reservation_id):
    decision, reservation = repository.reserve_order(
        reservation_id=reservation_id,
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=500.0, leverage=1.0,
        ),
    )
    assert decision.allowed
    assert reservation is not None
    return reservation


def test_release_and_reservation_queries_are_scoped_to_the_exact_account(tmp_path):
    repository = SQLiteAccountRiskRepository(str(tmp_path / "reservation-scope.sqlite"))
    scope_a, scope_b = _scope("account-a", "99501"), _scope("account-b", "99502")
    reservation_a, reservation_b = "QE-phase325-a", "QE-phase325-b"
    try:
        for scope in (scope_a, scope_b):
            repository.register(
                scope=scope, profile=_profile(),
                initial_state=AccountRiskState(
                    scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
                ),
            )
        _reserve(repository, scope_a, reservation_a)
        _reserve(repository, scope_b, reservation_b)

        assert [item.reservation_id for item in repository.list_pending_reservations(scope_a)] == [reservation_a]
        assert [item.reservation_id for item in repository.list_pending_reservations(scope_b)] == [reservation_b]

        # A different account must not release another account's reservation.
        with pytest.raises(AccountRiskError, match="scope mismatch"):
            repository.release_reservation(scope=scope_b, reservation_id=reservation_a)

        assert repository.release_reservation(scope=scope_a, reservation_id=reservation_a) is True
        assert repository.release_reservation(scope=scope_a, reservation_id=reservation_a) is False
        assert repository.list_pending_reservations(scope_a) == ()
        assert [item.reservation_id for item in repository.list_pending_reservations(scope_b)] == [reservation_b]

        _, state_a = repository.get(scope_a)
        _, state_b = repository.get(scope_b)
        assert (state_a.pending_orders, state_a.pending_exposure, state_a.revision) == (0, 0.0, 2)
        assert (state_b.pending_orders, state_b.pending_exposure, state_b.revision) == (1, 500.0, 1)
    finally:
        repository.close()
