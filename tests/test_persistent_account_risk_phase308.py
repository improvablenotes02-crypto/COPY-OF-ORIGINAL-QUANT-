"""Phase 308: durable revisioned per-account risk state repository."""
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
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
)


def _scope(tenant="tenant-a", account="internal-1", provider="12345"):
    return AccountRiskScope(
        tenant_id=tenant, account_id=account, provider_account_id=provider,
        region="INDIA", environment="SANDBOX",
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
    values = dict(
        scope=scope, risk_basis=10000.0, equity=10000.0,
        daily_pnl=0.0, weekly_pnl=0.0, monthly_pnl=0.0,
        open_positions=0, pending_orders=0, current_exposure=0.0,
        pending_exposure=0.0, kill_switch=False, trading_enabled=True,
        revision=0,
    )
    values.update(changes)
    return AccountRiskState(**values)


def test_risk_state_survives_repository_reopen(tmp_path):
    path = str(tmp_path / "account-risk.sqlite")
    scope = _scope()
    first = SQLiteAccountRiskRepository(path)
    PersistentAccountRiskCoordinator(first).register(
        scope=scope, profile=_profile(), initial_state=_state(scope)
    )
    first.close()

    second = SQLiteAccountRiskRepository(path)
    record = PersistentAccountRiskCoordinator(second).get_state(scope)
    assert record is not None
    profile, state = record
    assert profile == _profile()
    assert state == _state(scope)
    second.close()


def test_compare_and_swap_prevents_lost_risk_state_updates(tmp_path):
    path = str(tmp_path / "account-risk.sqlite")
    scope = _scope()
    repo_one, repo_two = SQLiteAccountRiskRepository(path), SQLiteAccountRiskRepository(path)
    coordinator_one = PersistentAccountRiskCoordinator(repo_one)
    coordinator_two = PersistentAccountRiskCoordinator(repo_two)
    coordinator_one.register(scope=scope, profile=_profile(), initial_state=_state(scope))

    stale_state = coordinator_two.get_state(scope)[1]
    updated = coordinator_one.update_state(
        scope=scope, expected_revision=0,
        state=replace(stale_state, daily_pnl=-100.0),
    )
    assert updated.revision == 1

    with pytest.raises(AccountRiskError, match="stale"):
        coordinator_two.update_state(
            scope=scope, expected_revision=0,
            state=replace(stale_state, weekly_pnl=-200.0),
        )
    persisted = coordinator_two.get_state(scope)[1]
    assert persisted.revision == 1
    assert persisted.daily_pnl == -100.0
    assert persisted.weekly_pnl == 0.0
    repo_one.close()
    repo_two.close()


def test_tenant_account_keys_are_isolated(tmp_path):
    repo = SQLiteAccountRiskRepository(str(tmp_path / "risk.sqlite"))
    first, second = _scope("tenant-a"), _scope("tenant-b")
    coordinator = PersistentAccountRiskCoordinator(repo)
    coordinator.register(scope=first, profile=_profile(), initial_state=_state(first))
    coordinator.register(scope=second, profile=_profile(), initial_state=_state(second))
    assert coordinator.get_state(first)[1].scope.tenant_id == "tenant-a"
    assert coordinator.get_state(second)[1].scope.tenant_id == "tenant-b"
    repo.close()


def test_repository_backed_risk_evaluation_uses_persisted_account_state(tmp_path):
    repo = SQLiteAccountRiskRepository(str(tmp_path / "risk.sqlite"))
    scope = _scope()
    coordinator = PersistentAccountRiskCoordinator(repo)
    coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope))
    proposal = OrderRiskProposal(
        scope=scope, risk_amount=50.0, notional=500.0, leverage=1.0,
    )
    assert coordinator.evaluate(proposal).allowed is True
    repo.close()


def test_non_finite_state_is_rejected_before_persistence(tmp_path):
    repo = SQLiteAccountRiskRepository(str(tmp_path / "risk.sqlite"))
    scope = _scope()
    with pytest.raises(AccountRiskError, match="serializable"):
        repo.register(
            scope=scope, profile=_profile(),
            initial_state=_state(scope, equity=float("nan")),
        )
    repo.close()


def test_revision_must_be_non_negative_integer():
    scope = _scope()
    with pytest.raises(ValueError, match="revision"):
        _state(scope, revision=-1)
