"""Phase 311: concurrent atomic reservations share one exposure budget."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from core.accounts.account_risk import (
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import (
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
)


def test_simultaneous_reservations_cannot_both_consume_same_exposure_headroom(tmp_path):
    path = str(tmp_path / "reservation-race.sqlite")
    scope = AccountRiskScope(
        tenant_id="tenant-atomic", account_id="account-atomic",
        provider_account_id="77123", region="INDIA", environment="SANDBOX",
    )
    profile = AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=0.15, max_open_positions=10,
        max_pending_orders=5,
    )
    repo_a, repo_b = SQLiteAccountRiskRepository(path), SQLiteAccountRiskRepository(path)
    coordinator_a = PersistentAccountRiskCoordinator(repo_a)
    coordinator_b = PersistentAccountRiskCoordinator(repo_b)
    coordinator_a.register(
        scope=scope, profile=profile,
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    proposal = OrderRiskProposal(
        scope=scope, risk_amount=50.0, notional=1000.0, leverage=1.0,
    )
    barrier = Barrier(2)

    def reserve(coordinator, reservation_id):
        barrier.wait()
        return coordinator.reserve_order(
            reservation_id=reservation_id, proposal=proposal
        )[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(reserve, coordinator_a, "concurrent-order-a"),
            pool.submit(reserve, coordinator_b, "concurrent-order-b"),
        ]
        decisions = [future.result(timeout=15) for future in futures]

    assert sum(decision.allowed for decision in decisions) == 1
    assert sum(decision.reason == "MAX_TOTAL_EXPOSURE" for decision in decisions) == 1
    state = coordinator_a.get_state(scope)[1]
    assert state.pending_orders == 1
    assert state.pending_exposure == 1000.0
    repo_a.close()
    repo_b.close()
