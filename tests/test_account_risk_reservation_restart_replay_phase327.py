"""Phase 327: pending account-risk reservations survive restart without replay."""
import pytest

from core.accounts.account_risk import (
    AccountRiskError, AccountRiskProfile, AccountRiskScope, AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository


def _scope(account, provider):
    return AccountRiskScope(
        tenant_id="tenant-phase327", account_id=account,
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


def _proposal(scope):
    return OrderRiskProposal(
        scope=scope, risk_amount=25.0, notional=500.0, leverage=1.0,
    )


def test_pending_reservation_survives_restart_and_duplicate_id_never_replays(tmp_path):
    database = str(tmp_path / "reservation-restart.sqlite")
    scope_a, scope_b = _scope("account-a", "99701"), _scope("account-b", "99702")
    reservation_id = "QE-phase327-durable-reservation"

    first = SQLiteAccountRiskRepository(database)
    for scope in (scope_a, scope_b):
        first.register(
            scope=scope, profile=_profile(),
            initial_state=AccountRiskState(
                scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
            ),
        )
    decision, reservation = first.reserve_order(
        reservation_id=reservation_id, proposal=_proposal(scope_a),
    )
    assert decision.allowed and reservation is not None
    assert reservation.status == "PENDING"
    _, reserved_state = first.get(scope_a)
    assert (reserved_state.pending_orders, reserved_state.pending_exposure) == (1, 500.0)
    first.close()

    recovered = SQLiteAccountRiskRepository(database)
    try:
        pending = recovered.list_pending_reservations(scope_a)
        assert len(pending) == 1
        assert pending[0].reservation_id == reservation_id
        assert pending[0].status == "PENDING"
        _, recovered_state = recovered.get(scope_a)
        assert recovered_state == reserved_state

        # Idempotent replay of the exact proposal returns the existing reservation.
        replay_decision, replay = recovered.reserve_order(
            reservation_id=reservation_id, proposal=_proposal(scope_a),
        )
        assert replay_decision.allowed
        assert replay is not None and replay.status == "PENDING"
        _, after_replay = recovered.get(scope_a)
        assert after_replay == recovered_state

        # Global reservation IDs cannot be rebound to another account after restart.
        with pytest.raises(AccountRiskError, match="already bound"):
            recovered.reserve_order(
                reservation_id=reservation_id, proposal=_proposal(scope_b),
            )
        _, untouched_b = recovered.get(scope_b)
        assert untouched_b.pending_orders == 0
        assert untouched_b.pending_exposure == 0.0
        assert untouched_b.revision == 0

        assert recovered.release_reservation(
            scope=scope_a, reservation_id=reservation_id,
        ) is True
        recovered.close()

        final = SQLiteAccountRiskRepository(database)
        try:
            assert final.list_pending_reservations(scope_a) == ()
            rejected, no_reservation = final.reserve_order(
                reservation_id=reservation_id, proposal=_proposal(scope_a),
            )
            assert not rejected.allowed
            assert no_reservation is None
            _, final_state = final.get(scope_a)
            assert final_state.pending_orders == 0
            assert final_state.pending_exposure == 0.0
            assert final_state.revision == recovered_state.revision + 1
        finally:
            final.close()
    except Exception:
        try:
            recovered.close()
        except Exception:
            pass
        raise
