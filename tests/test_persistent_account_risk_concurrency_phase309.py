"""Phase 309: simultaneous risk-state writers cannot lose an update."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

from core.accounts.account_risk import (
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    AccountRiskError,
)
from core.accounts.persistent_account_risk import (
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
)


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-race", account_id="internal-race",
        provider_account_id="99123", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_two_simultaneous_writers_cannot_overwrite_same_revision(tmp_path):
    path = str(tmp_path / "risk-concurrency.sqlite")
    scope = _scope()
    repo_a = SQLiteAccountRiskRepository(path)
    repo_b = SQLiteAccountRiskRepository(path)
    coordinator_a = PersistentAccountRiskCoordinator(repo_a)
    coordinator_b = PersistentAccountRiskCoordinator(repo_b)
    initial = AccountRiskState(
        scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
    )
    coordinator_a.register(scope=scope, profile=_profile(), initial_state=initial)
    snapshot_a = coordinator_a.get_state(scope)[1]
    snapshot_b = coordinator_b.get_state(scope)[1]
    barrier = Barrier(2)

    def attempt(coordinator, snapshot, pnl):
        barrier.wait()
        try:
            return coordinator.update_state(
                scope=scope, expected_revision=0,
                state=replace(snapshot, daily_pnl=pnl),
            )
        except AccountRiskError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(attempt, coordinator_a, snapshot_a, -100.0),
            pool.submit(attempt, coordinator_b, snapshot_b, -200.0),
        ]
        results = [future.result(timeout=15) for future in futures]

    winners = [value for value in results if value != "stale"]
    stale = [value for value in results if value == "stale"]
    assert len(winners) == 1
    assert len(stale) == 1
    assert winners[0].revision == 1
    persisted = coordinator_a.get_state(scope)[1]
    assert persisted.revision == 1
    assert persisted.daily_pnl in (-100.0, -200.0)
    repo_a.close()
    repo_b.close()
