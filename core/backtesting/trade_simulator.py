"""
====================================================

Institutional Trade Simulator

====================================================
"""

from core.backtesting.accounting import (
    gross_pnl,
    net_pnl,
    position_return_percent,
)
from core.backtesting.trade import Trade
from core.backtesting.trade_registry import TradeRegistry

from core.common.logging_config import get_logger
from core.risk.costs import post_cost_rr, post_cost_trailing
from core.risk.position_manager import PositionManager
from core.execution.economics import FundingSchedule
from config import risk_settings

import math

log = get_logger(__name__)


class TradeSimulator:

    def __init__(self, position_manager=None, funding_schedule=None):

        self.registry = TradeRegistry()

        self.current_trade = None

        if funding_schedule is not None and not isinstance(funding_schedule, FundingSchedule):
            raise TypeError("funding_schedule must be a FundingSchedule")
        self.funding_schedule = funding_schedule

        # Execution-layer quantity hygiene enforced by the
        # SHARED PositionManager at the single choke point every
        # mode (Backtest / Paper / Live Broker) passes through.
        self.position_manager = (
            position_manager
            if position_manager is not None
            else PositionManager()
        )

    # -------------------------------------------------

    def open_trade(

        self,

        setup,

        timestamp,

        quantity=1.0,

        commission=0.0,

        slippage=0.0,

    ):

        if self.current_trade is not None:

            return None

        # Refine the order (rounding, notional cap, dust drop)
        # BEFORE it becomes a position so every mode books the
        # same corrected quantity. manage() never mutates the
        # caller's order.
        pre_quantity = float(getattr(setup, "quantity", quantity))

        setup = self.position_manager.manage(setup)

        quantity = float(getattr(setup, "quantity", quantity))

        entry = float(setup.entry)

        stop_loss = float(setup.stop_loss)

        take_profit = float(getattr(setup, "take_profit", 0.0) or 0.0)
        exit_mode = str(getattr(setup, "exit_mode", "FIXED_TARGET") or "FIXED_TARGET").upper()
        trailing_activation_r = float(getattr(setup, "trailing_activation_r", 0.0) or 0.0)
        trailing_distance_r = float(getattr(setup, "trailing_distance_r", 0.0) or 0.0)
        trailing_enabled = bool(getattr(setup, "trailing_enabled", exit_mode == "TRAILING_STOP"))

        # Fail closed (11E-Prep C1-C): the executable
        # quantity must be finite AND > 0. `quantity <= 0`
        # alone is not sufficient because NaN <= 0 is False
        # and a NaN quantity would otherwise become a Trade.
        # Entry/stop/take-profit must be finite too: they
        # price the fill and size the risk booked on the
        # trade.
        if exit_mode not in ("FIXED_TARGET", "TRAILING_STOP"):
            return None
        if exit_mode == "TRAILING_STOP":
            if not trailing_enabled:
                return None
            initial_risk = abs(entry - stop_loss)
            if initial_risk <= 0 or trailing_activation_r <= 0 or trailing_distance_r <= 0:
                return None
        if not (
            math.isfinite(quantity)
            and math.isfinite(entry)
            and math.isfinite(stop_loss)
            and math.isfinite(take_profit)
            and math.isfinite(trailing_activation_r)
            and math.isfinite(trailing_distance_r)
            and quantity > 0
        ):

            return None

        # Phase 13 mandatory post-cost R:R validation (single
        # authority: core.risk.costs.post_cost_rr). This is the ONE
        # fill choke point every executable mode (Backtest, Paper,
        # Live Broker dry-run, plus the legacy signal fallback)
        # passes through, so no mode and no fallback can bypass
        # cost-aware validation. Layering contract (explicit):
        #
        #   * Non-finite commission/slippage ALWAYS fails closed —
        #     corrupt economics can never become a position.
        #   * Zero costs (commission == 0 and slippage == 0) leave
        #     behavior byte-identical to the pre-gate path: there is
        #     no erosion to validate, and gross R:R remains the duty
        #     of the upstream Decision / Risk / mode fill gates
        #     (all wired). The gate is the COST-aware layer, not a
        #     second gross gate.
        #   * Nonzero costs shift the entry adversely (LONG up /
        #     SHORT down, symmetric) and the fill is REFUSED when
        #     post-cost R:R falls below the active minimum-R policy
        #     — BEFORE any mutation (no Trade is constructed, the
        #     caller's order is untouched) and WITHOUT altering
        #     booking: the same commission/slippage are still
        #     subtracted exactly once at close via
        #     accounting.net_pnl.
        commission_f = float(commission)
        slippage_f = float(slippage)
        if not (math.isfinite(commission_f)
                and math.isfinite(slippage_f)):

            log.error(
                "OPEN_TRADE_BLOCKED_NON_FINITE_COSTS setup_id=%s",
                getattr(setup, "setup_id", "") or "",
            )

            return None

        if commission_f != 0.0 or slippage_f != 0.0:

            try:
                direction = str(setup.direction).upper()
            except Exception:  # noqa: BLE001 (fail closed)
                direction = ""

            if exit_mode == "TRAILING_STOP":
                verdict = post_cost_trailing(
                    direction=direction, entry=entry, stop=stop_loss,
                    quantity=quantity, commission=commission_f,
                    slippage=slippage_f, target=take_profit,
                    symbol=getattr(setup, "symbol", None),
                )
            else:
                verdict = post_cost_rr(
                    direction=direction, entry=entry, stop=stop_loss,
                    target=take_profit, quantity=quantity,
                    commission=commission_f, slippage=slippage_f,
                    exit_mode=exit_mode,
                    symbol=getattr(setup, "symbol", None),
                )

            if not verdict.allowed:

                log.error(
                    "OPEN_TRADE_BLOCKED_POST_COST_RR setup_id=%s "
                    "direction=%s rr=%.4f reason=%s",
                    getattr(setup, "setup_id", "") or "",
                    direction,
                    verdict.rr,
                    verdict.reason,
                )

                return None

        # Actual risk from the FINAL executable quantity
        # (11E-Prep H1-C): only when the manager changed the
        # quantity (allocation cap, dust, rounding) is the
        # order's risk_amount stale — then the trade books
        # final_quantity x stop_distance. Otherwise the
        # order's own risk_amount is preserved verbatim
        # (scripted/authored flows carry it independently).
        if quantity != pre_quantity:
            final_risk_amount = quantity * abs(entry - stop_loss)
        else:
            final_risk_amount = float(
                getattr(setup, "risk_amount", 0.0)
            )

        trade = Trade(

            direction=setup.direction,

            entry=setup.entry,

            stop_loss=setup.stop_loss,

            take_profit=setup.take_profit,

            exit_mode=exit_mode,
            trailing_activation_r=trailing_activation_r,
            trailing_distance_r=trailing_distance_r,
            trailing_enabled=trailing_enabled,
            initial_stop_loss=stop_loss,

            quantity=quantity,

            risk_amount=final_risk_amount,

            commission=commission,

            slippage=slippage,

            entry_time=timestamp,

            setup_score=getattr(setup, "score", 0.0),

            confidence=getattr(setup, "confidence", 0.0),

            symbol=getattr(setup, "symbol", ""),

            # Phase 4C identity chain: carried from the order at
            # open time; trade_id is completed by the mode adapter
            # via OrderRegistry.mark_filled.
            setup_id=getattr(setup, "setup_id", ""),

            order_id=getattr(setup, "order_id", ""),

            # Phase 4F: the entry model the order was opened under.
            entry_mode=getattr(setup, "entry_mode", ""),

            # Phase 6C: the canonical setup identity carried
            # unchanged from the OrderIntent at open time.
            canonical_id=getattr(setup, "canonical_id", ""),

        )

        try:
            trade.validate_executable()
        except ValueError as err:
            log.error(
                "OPEN_TRADE_VALIDATION_FAILED setup_id=%s reason=%s",
                getattr(setup, "setup_id", "") or "",
                err,
            )
            return None

        self.current_trade = trade

        return trade

    # -------------------------------------------------

    def update(

        self,

        candle,

    ):

        trade = self.current_trade

        if trade is None:
            return

        trade.bars_held += 1
        is_bull = trade.direction == "BULLISH"

        if trade.exit_mode == "TRAILING_STOP" and trade.trailing_enabled:
            initial_risk = abs(trade.entry - getattr(trade, "initial_stop_loss", trade.stop_loss))
            activation = initial_risk * trade.trailing_activation_r
            distance = initial_risk * trade.trailing_distance_r

            active_stop = trade.stop_loss
            hit_sl = (candle.low <= active_stop) if is_bull else (candle.high >= active_stop)
            hit_tp = (candle.high >= trade.take_profit) if is_bull else (candle.low <= trade.take_profit)
            if hit_sl and hit_tp:
                self._close_trade(candle.timestamp, active_stop, "LOSS", ambiguous=True)
                return
            if hit_sl:
                self._close_trade(candle.timestamp, active_stop, "LOSS")
                return
            if hit_tp and trade.take_profit:
                self._close_trade(candle.timestamp, trade.take_profit, "WIN")
                return

            # Trail from completed close; the new stop is active next candle.
            favorable = (float(candle.close) - trade.entry) if is_bull else (trade.entry - float(candle.close))
            if favorable >= activation:
                if is_bull:
                    proposed = float(candle.close) - distance
                    if proposed > trade.stop_loss:
                        trade.stop_loss = proposed
                else:
                    proposed = float(candle.close) + distance
                    if proposed < trade.stop_loss:
                        trade.stop_loss = proposed
            return

        hit_sl = (candle.low <= trade.stop_loss) if is_bull else (candle.high >= trade.stop_loss)
        hit_tp = (candle.high >= trade.take_profit) if is_bull else (candle.low <= trade.take_profit)
        ambiguous = hit_sl and hit_tp

        if is_bull:
            if hit_sl:
                self._close_trade(candle.timestamp, trade.stop_loss, "LOSS", ambiguous=ambiguous)
                return
            if hit_tp:
                self._close_trade(candle.timestamp, trade.take_profit, "WIN", ambiguous=ambiguous)
                return
        else:
            if hit_sl:
                self._close_trade(candle.timestamp, trade.stop_loss, "LOSS", ambiguous=ambiguous)
                return
            if hit_tp:
                self._close_trade(candle.timestamp, trade.take_profit, "WIN", ambiguous=ambiguous)
                return

    # -------------------------------------------------

    def request_exit(self, timestamp, exit_price, reason="SIGNAL_EXIT"):
        """Close an open trade at the supplied observed price.

        This is the deterministic runtime escape hatch for an explicit
        QuantEngine exit/book-profit signal. It never fabricates a price:
        callers must provide the observed market price.
        """
        trade = self.current_trade
        if trade is None:
            return False
        pnl = gross_pnl(trade.direction, trade.entry, float(exit_price), trade.quantity)
        result = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
        self._close_trade(timestamp, float(exit_price), result, reason=str(reason))
        return True

    def _close_trade(

        self,

        timestamp,

        exit_price,

        result,

        ambiguous: bool = False,
        reason: str = "",

    ):

        trade = self.current_trade

        trade.exit_time = timestamp

        trade.exit_price = exit_price

        trade.result = result
        trade.exit_reason = str(reason or "")

        trade.status = "CLOSED"

        trade.ambiguous = bool(ambiguous)

        gross = gross_pnl(trade.direction, trade.entry, exit_price, trade.quantity)

        # Net of round-trip commission + slippage. Both
        # default to 0.0 on the fixed-quantity legacy path,
        # where net == gross. Canonical accounting.
        funding_cost = 0.0
        funding_events = 0
        if self.funding_schedule is not None:
            funding_cost, funding_events = self.funding_schedule.cost(
                entry_time=int(trade.entry_time), exit_time=int(trade.exit_time),
                direction=trade.direction, entry=trade.entry, quantity=trade.quantity)
        trade.funding = funding_cost
        trade.funding_events = funding_events
        trade.pnl = net_pnl(gross, trade.commission, trade.slippage, funding_cost)

        trade.pnl_percent = position_return_percent(trade.pnl, trade.entry, trade.quantity)

        self.registry.add(trade)

        self.current_trade = None

        # Phase 4C: identity-based TRADE_CLOSED at the single
        # close choke point shared by Backtest / Paper / Live.
        if trade.trade_id or trade.order_id:

            log.info(
                "TRADE_CLOSED setup_id=%s order_id=%s "
                "trade_id=%s result=%s pnl=%.2f ts=%s",
                trade.setup_id,
                trade.order_id,
                trade.trade_id,
                trade.result,
                trade.pnl,
                timestamp,
            )

    # -------------------------------------------------

    def reset(self):

        self.registry.clear()

        self.current_trade = None