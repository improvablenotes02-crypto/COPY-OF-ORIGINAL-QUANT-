"""Phase 287: account-specific risk profiles and mutable state isolation."""
import math

import pytest

from core.accounts.account_risk import (
    AccountRiskCoordinator,
    AccountRiskError,
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    OrderRiskProposal,
)


def _scope(tenant="tenant-a", account="acct-1", provider="123", region="INDIA", environment="SANDBOX"):
    return AccountRiskScope(
        tenant_id=tenant, account_id=account, provider_account_id=provider,
        region=region, environment=environment,
    )


def _profile(**overrides):
    values = {
        "risk_per_trade_fraction": 0.01,
        "max_order_notional": 1000.0,
        "max_leverage": 5.0,
        "max_daily_loss_fraction": 0.02,
        "max_weekly_loss_fraction": 0.05,
        "max_monthly_loss_fraction": 0.10,
        "max_total_exposure_fraction": 4.0,
        "max_open_positions": 3,
        "max_pending_orders": 5,
    }
    values.update(overrides)
    return AccountRiskProfile(**values)


def _state(scope, **overrides):
    values = {
        "scope": scope,
        "risk_basis": 10000.0,
        "equity": 10000.0,
    }
    values.update(overrides)
    return AccountRiskState(**values)


def _proposal(scope, **overrides):
    values = {"scope": scope, "risk_amount": 50.0, "notional": 500.0, "leverage": 1.0}
    values.update(overrides)
    return OrderRiskProposal(**values)


def test_two_tenants_have_independent_profiles_and_risk_state():
    scope_a = _scope("tenant-a", "acct-1", "123")
    scope_b = _scope("tenant-b", "acct-2", "456")
    coordinator = AccountRiskCoordinator()
    coordinator.register(scope=scope_a, profile=_profile(), initial_state=_state(scope_a))
    coordinator.register(
        scope=scope_b,
        profile=_profile(risk_per_trade_fraction=0.005, max_order_notional=100.0),
        initial_state=_state(scope_b),
    )
    assert coordinator.evaluate(_proposal(scope_a)).allowed is True
    denied = coordinator.evaluate(_proposal(scope_b))
    assert denied.allowed is False
    assert denied.reason == "MAX_ORDER_NOTIONAL_EXCEEDED"


def test_same_internal_account_id_cannot_cross_tenant_boundary():
    scope_a = _scope("tenant-a", "shared-id", "123")
    scope_b = _scope("tenant-b", "shared-id", "456")
    coordinator = AccountRiskCoordinator()
    coordinator.register(scope=scope_a, profile=_profile(), initial_state=_state(scope_a))
    denied = coordinator.evaluate(_proposal(scope_b))
    assert denied.allowed is False
    assert denied.reason == "ACCOUNT_RISK_PROFILE_MISSING"


def test_provider_identity_region_or_environment_mismatch_is_denied():
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope))
    mismatches = [
        _scope(provider="999"),
        _scope(region="GLOBAL"),
        _scope(environment="PRODUCTION"),
    ]
    for wrong_scope in mismatches:
        decision = coordinator.evaluate(_proposal(wrong_scope))
        assert decision.allowed is False
        assert decision.reason == "ACCOUNT_SCOPE_MISMATCH"


def test_risk_profile_is_mandatory_and_duplicate_registration_is_refused():
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    assert coordinator.evaluate(_proposal(scope)).reason == "ACCOUNT_RISK_PROFILE_MISSING"
    coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope))
    with pytest.raises(AccountRiskError, match="already registered"):
        coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope))


def test_kill_switch_and_trading_disabled_are_account_local_hard_blocks():
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope, kill_switch=True))
    assert coordinator.evaluate(_proposal(scope)).reason == "ACCOUNT_KILL_SWITCH_ACTIVE"

    scope2 = _scope(account="acct-2", provider="124")
    coordinator.register(scope=scope2, profile=_profile(), initial_state=_state(scope2, trading_enabled=False))
    assert coordinator.evaluate(_proposal(scope2)).reason == "ACCOUNT_TRADING_DISABLED"


@pytest.mark.parametrize(
    "field,limit,reason",
    [
        ("daily_pnl", -200.0, "DAILY_LOSS_LIMIT"),
        ("weekly_pnl", -500.0, "WEEKLY_LOSS_LIMIT"),
        ("monthly_pnl", -1000.0, "MONTHLY_LOSS_LIMIT"),
    ],
)
def test_exact_loss_limit_boundary_blocks_new_risk(field, limit, reason):
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=_state(scope, **{field: limit}),
    )
    decision = coordinator.evaluate(_proposal(scope))
    assert decision.allowed is False
    assert decision.reason == reason


@pytest.mark.parametrize(
    "state_overrides,reason",
    [
        ({"open_positions": 3}, "MAX_OPEN_POSITIONS"),
        ({"pending_orders": 5}, "MAX_PENDING_ORDERS"),
        ({"current_exposure": 40000.0}, "MAX_TOTAL_EXPOSURE"),
        ({"pending_exposure": 40000.0}, "MAX_TOTAL_EXPOSURE"),
    ],
)
def test_position_and_aggregate_exposure_caps_block(state_overrides, reason):
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    coordinator.register(
        scope=scope, profile=_profile(), initial_state=_state(scope, **state_overrides)
    )
    assert coordinator.evaluate(_proposal(scope)).reason == reason


@pytest.mark.parametrize(
    "proposal_overrides,reason",
    [
        ({"risk_amount": 101.0}, "RISK_PER_TRADE_EXCEEDED"),
        ({"notional": 1001.0}, "MAX_ORDER_NOTIONAL_EXCEEDED"),
        ({"leverage": 6.0}, "MAX_LEVERAGE_EXCEEDED"),
        ({"notional": 500.0, "leverage": 0.01}, "DECLARED_LEVERAGE_UNDERSTATES_EXPOSURE"),
        ({"notional": 30000.0, "leverage": 5.0}, "MAX_ORDER_NOTIONAL_EXCEEDED"),
    ],
)
def test_order_proposal_limits_are_enforced(proposal_overrides, reason):
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope))
    decision = coordinator.evaluate(_proposal(scope, **proposal_overrides))
    assert decision.allowed is False
    assert decision.reason == reason


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -1.0, True])
def test_non_finite_or_negative_capital_and_exposure_fail_closed(bad_value):
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=_state(scope, equity=bad_value),
    )
    assert coordinator.evaluate(_proposal(scope)).reason == "ACCOUNT_CAPITAL_INVALID"


def test_invalid_pnl_and_exposure_fail_closed():
    scope = _scope()
    coordinator = AccountRiskCoordinator()
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=_state(scope, daily_pnl=math.nan),
    )
    assert coordinator.evaluate(_proposal(scope)).reason == "ACCOUNT_PNL_INVALID"

    scope2 = _scope(account="acct-2", provider="124")
    coordinator.register(
        scope=scope2, profile=_profile(),
        initial_state=_state(scope2, current_exposure=math.inf),
    )
    assert coordinator.evaluate(_proposal(scope2)).reason == "ACCOUNT_EXPOSURE_INVALID"


def test_state_update_cannot_change_account_scope():
    scope = _scope()
    other = _scope(tenant="tenant-b", account="acct-2", provider="456")
    coordinator = AccountRiskCoordinator()
    coordinator.register(scope=scope, profile=_profile(), initial_state=_state(scope))
    with pytest.raises(AccountRiskError, match="scope"):
        coordinator.update_state(scope=scope, state=_state(other))


def test_risk_profile_rejects_unbounded_or_inconsistent_limits():
    with pytest.raises(ValueError, match="risk fractions"):
        _profile(risk_per_trade_fraction=0.0)
    with pytest.raises(ValueError, match="max_total_exposure_fraction"):
        _profile(max_total_exposure_fraction=6.0)


def test_account_scope_rejects_invalid_provider_identity_and_venue():
    with pytest.raises(ValueError, match="provider_account_id"):
        _scope(provider="0")
    with pytest.raises(ValueError, match="venue"):
        AccountRiskScope("t", "a", "123", "INDIA", "SANDBOX", venue="other")
