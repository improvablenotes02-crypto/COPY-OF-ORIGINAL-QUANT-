"""Per-tenant, per-Delta-account risk policy and state isolation.

This module is an account-scoped preflight boundary. It does not submit
orders and does not replace the existing single-account RiskEngine. A
multi-account executor must call this gate for each account before it can
request any separately authorized execution action.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading

from core.exchanges.delta import delta_environments


class AccountRiskError(RuntimeError):
    """Account risk profile or state is invalid."""


@dataclass(frozen=True, slots=True)
class AccountRiskScope:
    tenant_id: str
    account_id: str
    provider_account_id: str
    region: str
    environment: str
    venue: str = "delta"

    def __post_init__(self):
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise ValueError("tenant_id is required")
        if not isinstance(self.account_id, str) or not self.account_id.strip():
            raise ValueError("account_id is required")
        if (
            not isinstance(self.provider_account_id, str)
            or not self.provider_account_id.isdigit()
            or int(self.provider_account_id) <= 0
        ):
            raise ValueError("provider_account_id must be a positive decimal ID")
        if self.venue != "delta":
            raise ValueError("only the Delta venue is supported")
        if delta_environments.resolve_region(self.region) == delta_environments.UNKNOWN_REGION:
            raise ValueError("unsupported Delta region")
        if delta_environments.resolve_environment(self.environment) == delta_environments.UNKNOWN:
            raise ValueError("unsupported Delta environment")
        object.__setattr__(self, "region", delta_environments.resolve_region(self.region))
        object.__setattr__(self, "environment", delta_environments.resolve_environment(self.environment))


@dataclass(frozen=True, slots=True)
class AccountRiskProfile:
    risk_per_trade_fraction: float
    max_order_notional: float
    max_leverage: float
    max_daily_loss_fraction: float
    max_weekly_loss_fraction: float
    max_monthly_loss_fraction: float
    max_open_positions: int
    max_pending_orders: int

    def __post_init__(self):
        fractions = (
            self.risk_per_trade_fraction,
            self.max_daily_loss_fraction,
            self.max_weekly_loss_fraction,
            self.max_monthly_loss_fraction,
        )
        for value in fractions:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("risk fractions must be numeric")
            if not math.isfinite(float(value)) or not 0.0 < float(value) <= 1.0:
                raise ValueError("risk fractions must be finite and in (0, 1]")
        for name, value in (
            ("max_order_notional", self.max_order_notional),
            ("max_leverage", self.max_leverage),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value in (
            ("max_open_positions", self.max_open_positions),
            ("max_pending_orders", self.max_pending_orders),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class AccountRiskState:
    scope: AccountRiskScope
    risk_basis: float
    equity: float
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    open_positions: int = 0
    pending_orders: int = 0
    kill_switch: bool = False


@dataclass(frozen=True, slots=True)
class OrderRiskProposal:
    scope: AccountRiskScope
    risk_amount: float
    notional: float
    leverage: float


@dataclass(frozen=True, slots=True)
class AccountRiskDecision:
    allowed: bool
    reason: str
    scope: AccountRiskScope
    maximum_risk_amount: float
    maximum_notional: float


def _finite_positive(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0
    )


class AccountRiskGate:
    """Pure account-scoped risk decision; no state mutation or network I/O."""

    @staticmethod
    def evaluate(
        profile: AccountRiskProfile,
        state: AccountRiskState,
        proposal: OrderRiskProposal,
    ) -> AccountRiskDecision:
        scope = proposal.scope
        maximum_risk = 0.0
        maximum_notional = 0.0

        def deny(reason: str) -> AccountRiskDecision:
            return AccountRiskDecision(False, reason, scope, maximum_risk, maximum_notional)

        if not isinstance(profile, AccountRiskProfile):
            return deny("RISK_PROFILE_INVALID")
        if not isinstance(state, AccountRiskState):
            return deny("RISK_STATE_INVALID")
        if state.scope != scope:
            return deny("ACCOUNT_SCOPE_MISMATCH")
        if not isinstance(state.kill_switch, bool):
            return deny("KILL_SWITCH_STATE_INVALID")
        if state.kill_switch:
            return deny("ACCOUNT_KILL_SWITCH_ACTIVE")

        for value in (state.risk_basis, state.equity):
            if not _finite_positive(value):
                return deny("ACCOUNT_CAPITAL_INVALID")
        for value in (state.daily_pnl, state.weekly_pnl, state.monthly_pnl):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                return deny("ACCOUNT_PNL_INVALID")
        for value in (state.open_positions, state.pending_orders):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return deny("ACCOUNT_POSITION_COUNT_INVALID")

        maximum_risk = float(state.equity) * float(profile.risk_per_trade_fraction)
        maximum_notional = min(
            float(profile.max_order_notional),
            float(state.equity) * float(profile.max_leverage),
        )

        loss_windows = (
            ("DAILY_LOSS_LIMIT", state.daily_pnl, profile.max_daily_loss_fraction),
            ("WEEKLY_LOSS_LIMIT", state.weekly_pnl, profile.max_weekly_loss_fraction),
            ("MONTHLY_LOSS_LIMIT", state.monthly_pnl, profile.max_monthly_loss_fraction),
        )
        for reason, pnl, fraction in loss_windows:
            if float(pnl) <= -(float(state.risk_basis) * float(fraction)):
                return deny(reason)

        if state.open_positions >= profile.max_open_positions:
            return deny("MAX_OPEN_POSITIONS")
        if state.pending_orders >= profile.max_pending_orders:
            return deny("MAX_PENDING_ORDERS")

        for value in (proposal.risk_amount, proposal.notional, proposal.leverage):
            if not _finite_positive(value):
                return deny("ORDER_PROPOSAL_INVALID")
        if float(proposal.risk_amount) > maximum_risk:
            return deny("RISK_PER_TRADE_EXCEEDED")
        if float(proposal.notional) > maximum_notional:
            return deny("MAX_ORDER_NOTIONAL_EXCEEDED")
        if float(proposal.leverage) > float(profile.max_leverage):
            return deny("MAX_LEVERAGE_EXCEEDED")
        if float(proposal.notional) / float(state.equity) > float(profile.max_leverage):
            return deny("ACCOUNT_LEVERAGE_EXCEEDED")

        return AccountRiskDecision(
            True, "ACCOUNT_RISK_APPROVED", scope, maximum_risk, maximum_notional
        )


class AccountRiskCoordinator:
    """Thread-safe in-memory registry keyed by (tenant_id, internal account_id)."""

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], tuple[AccountRiskProfile, AccountRiskState]] = {}

    @staticmethod
    def _key(scope: AccountRiskScope) -> tuple[str, str]:
        return scope.tenant_id, scope.account_id

    def register(
        self, *, scope: AccountRiskScope, profile: AccountRiskProfile,
        initial_state: AccountRiskState,
    ) -> None:
        if not isinstance(scope, AccountRiskScope) or initial_state.scope != scope:
            raise AccountRiskError("initial risk state must match the registered account scope")
        if not isinstance(profile, AccountRiskProfile):
            raise AccountRiskError("an explicit account risk profile is required")
        key = self._key(scope)
        with self._lock:
            if key in self._entries:
                raise AccountRiskError("risk profile already registered for this tenant account")
            self._entries[key] = (profile, initial_state)

    def update_state(self, *, scope: AccountRiskScope, state: AccountRiskState) -> None:
        if not isinstance(scope, AccountRiskScope) or not isinstance(state, AccountRiskState):
            raise AccountRiskError("valid account scope and risk state are required")
        if state.scope != scope:
            raise AccountRiskError("risk state scope does not match account")
        key = self._key(scope)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry[1].scope != scope:
                raise AccountRiskError("risk profile not registered for this account scope")
            self._entries[key] = (entry[0], state)

    def evaluate(self, proposal: OrderRiskProposal) -> AccountRiskDecision:
        if not isinstance(proposal, OrderRiskProposal):
            raise ValueError("OrderRiskProposal is required")
        key = self._key(proposal.scope)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return AccountRiskDecision(
                False, "ACCOUNT_RISK_PROFILE_MISSING", proposal.scope, 0.0, 0.0
            )
        profile, state = entry
        return AccountRiskGate.evaluate(profile, state, proposal)
