"""Fail-closed structural checks for market adapters (Phase 200).

This module checks declarations and method shape only. It does not call an
adapter, connect to a venue, validate broker credentials, or prove that orders
are safe or supported by the remote API.
"""
from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

from core.exchanges.market_capabilities import MarketCapabilities

_READ_METHODS = ("get_products", "get_balance", "get_positions")
_ORDER_METHODS = ("place_order", "cancel_order", "get_order")
# Minimum positional arguments expected by the neutral adapter contract.
# Optional extra parameters are allowed; this checks shape, not semantics.
_METHOD_ARITY = {
    "get_products": 0,
    "get_balance": 0,
    "get_positions": 0,
    "place_order": 1,
    "cancel_order": 1,
    "get_order": 1,
}


@dataclass(frozen=True, slots=True)
class AdapterConformanceReport:
    adapter_name: str
    errors: tuple[str, ...]

    @property
    def conforms(self) -> bool:
        return not self.errors

    @property
    def live_execution_shape_valid(self) -> bool:
        # Structural readiness only; never equivalent to live authorization.
        return self.conforms


def validate_adapter_conformance(
    adapter: Any,
    capabilities: MarketCapabilities,
) -> AdapterConformanceReport:
    """Check required callable methods for declared adapter capabilities.

    Read methods are required for every adapter. Order methods are required
    only when the adapter declares live order support. Any claim of verified
    live execution must also satisfy the capability object's evidence gate.
    """
    errors: list[str] = []
    required_methods = _READ_METHODS + (_ORDER_METHODS if capabilities.live_orders else ())
    for method_name in required_methods:
        method = getattr(adapter, method_name, None)
        if not callable(method):
            if method_name in _READ_METHODS:
                errors.append(f"missing callable read method: {method_name}")
            else:
                errors.append(f"live_orders declared but method is missing: {method_name}")
            continue
        try:
            inspect.signature(method).bind(*([object()] * _METHOD_ARITY[method_name]))
        except (TypeError, ValueError):
            errors.append(
                f"method signature incompatible with adapter contract: {method_name}"
            )

    if capabilities.live_execution_eligible and not capabilities.live_orders:
        # Defensive invariant. Normally unreachable because eligibility itself
        # requires live_orders, but keep the check explicit for auditability.
        errors.append("live execution eligible without live_orders")

    return AdapterConformanceReport(capabilities.adapter_name, tuple(errors))


@dataclass(frozen=True, slots=True)
class AdapterBehaviorProbeReport:
    """Results of explicit, read-only adapter smoke probes.

    This probe invokes only the three shared read methods. It never invokes
    place_order/cancel_order and cannot certify remote truth or venue safety.
    """

    adapter_name: str
    products_count: int | None
    balance_type: str | None
    positions_count: int | None
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors


def probe_read_only_behavior(adapter: Any, adapter_name: str = "unknown") -> AdapterBehaviorProbeReport:
    """Run a bounded-shape smoke probe against a deliberately supplied adapter.

    Each method is called at most once. Products/positions must be list-like;
    balance must be mapping-like. Exceptions are converted to safe error labels
    without leaking exception messages, credentials, or response payloads.
    """
    from collections.abc import Mapping

    errors: list[str] = []
    products_count: int | None = None
    balance_type: str | None = None
    positions_count: int | None = None

    for method_name in _READ_METHODS:
        method = getattr(adapter, method_name, None)
        if not callable(method):
            errors.append(f"missing callable read method: {method_name}")
            continue
        try:
            value = method()
        except Exception as exc:  # adapter boundary: report class, not message
            errors.append(f"{method_name} raised {type(exc).__name__}")
            continue
        if method_name == "get_products":
            if not isinstance(value, (list, tuple)):
                errors.append("get_products must return list or tuple")
            else:
                products_count = len(value)
        elif method_name == "get_balance":
            if not isinstance(value, Mapping):
                errors.append("get_balance must return a mapping")
            else:
                balance_type = type(value).__name__
        elif method_name == "get_positions":
            if not isinstance(value, (list, tuple)):
                errors.append("get_positions must return list or tuple")
            else:
                positions_count = len(value)

    return AdapterBehaviorProbeReport(
        adapter_name=str(adapter_name),
        products_count=products_count,
        balance_type=balance_type,
        positions_count=positions_count,
        errors=tuple(errors),
    )
