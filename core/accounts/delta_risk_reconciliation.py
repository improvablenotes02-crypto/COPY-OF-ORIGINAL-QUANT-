"""Account-scoped Delta read-only reconciliation for pending risk reservations.

This orchestration layer never submits or cancels orders. It converts a
complete, identity-bound DeltaReadOnlySession snapshot into the dual-history
reconciliation evidence required by the persistent risk repository.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import time

from core.accounts.account_risk import AccountRiskError, AccountRiskScope, AccountRiskState
from core.accounts.delta_account_registry import DeltaReadOnlySession
from core.accounts.persistent_account_risk import (
    AccountRiskReconciliationEvidence,
    PersistentAccountRiskCoordinator,
)
from core.execution.delta_submission_reconciliation import reconcile_delta_submission


_TERMINAL_STATUS = {
    "FILLED": "FILLED",
    "REJECTED": "REJECTED",
    "CANCELLED": "CANCELED",
    "CANCELED": "CANCELED",
    "EXPIRED": "EXPIRED",
}


def _canonical_snapshot_hash(snapshot: dict) -> str:
    try:
        payload = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AccountRiskError("Delta account snapshot is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def reconcile_and_settle_pending_reservation(
    *,
    coordinator: PersistentAccountRiskCoordinator,
    journal,
    scope: AccountRiskScope,
    reservation_id: str,
    session: DeltaReadOnlySession,
    reconciled_state: AccountRiskState,
    now_ns: int | None = None,
    max_age_seconds: float = 30.0,
    max_snapshot_skew_seconds: float = 15.0,
) -> dict:
    """Settle only a terminal order proven by complete account-bound Delta reads.

    ACKNOWLEDGED, PARTIAL, missing, stale, contradictory, or incomplete
    observations leave the risk reservation pending. The supplied reconciled
    state must preserve all other pending reservations exactly.
    """
    if not isinstance(scope, AccountRiskScope):
        raise AccountRiskError("valid account risk scope is required")
    if not isinstance(session, DeltaReadOnlySession):
        raise AccountRiskError("a bound DeltaReadOnlySession is required")
    if (
        session.tenant_id != scope.tenant_id
        or session.account_id != scope.account_id
        or session.provider_account_id != scope.provider_account_id
        or session.region != scope.region
        or session.environment != scope.environment
    ):
        raise AccountRiskError("Delta read-only session does not match risk account scope")
    if not isinstance(reservation_id, str) or not reservation_id.strip():
        raise AccountRiskError("reservation_id is required")
    reservation_id = reservation_id.strip()
    if not isinstance(reconciled_state, AccountRiskState) or reconciled_state.scope != scope:
        raise AccountRiskError("reconciled risk state must match account scope")

    pending = coordinator.list_pending_reservations(scope)
    matches = [item for item in pending if item.reservation_id == reservation_id]
    if len(matches) != 1:
        raise AccountRiskError("exactly one pending risk reservation is required")
    reservation = matches[0]
    current_record = coordinator.get_state(scope)
    if current_record is None:
        raise AccountRiskError("account risk state is not registered")
    _, current_state = current_record
    if reconciled_state.revision != current_state.revision:
        raise AccountRiskError("reconciled risk state revision is stale")
    expected_pending_orders = current_state.pending_orders - 1
    expected_pending_exposure = current_state.pending_exposure - reservation.notional
    if expected_pending_orders < 0 or expected_pending_exposure < -1e-9:
        raise AccountRiskError("current risk state cannot cover pending reservation")
    if (
        reconciled_state.pending_orders != expected_pending_orders
        or not math.isclose(
            reconciled_state.pending_exposure,
            max(0.0, expected_pending_exposure),
            rel_tol=0.0, abs_tol=1e-9,
        )
    ):
        raise AccountRiskError("settlement would alter risk reserved by other pending orders")

    snapshot = session.get_account_snapshot()
    if (
        snapshot.get("venue") != "delta"
        or snapshot.get("tenant_id") != scope.tenant_id
        or snapshot.get("internal_account_id") != scope.account_id
        or snapshot.get("provider_account_id") != scope.provider_account_id
        or snapshot.get("region") != scope.region
        or snapshot.get("environment") != scope.environment
        or snapshot.get("observation_is_exchange_atomic") is not False
    ):
        raise AccountRiskError("Delta account snapshot identity or scope mismatch")
    completeness = snapshot.get("completeness")
    if not isinstance(completeness, dict) or any(
        completeness.get(key) is not True
        for key in (
            "balances", "positions", "orders", "fills",
            "order_cursor_exhausted", "fill_cursor_exhausted",
        )
    ):
        raise AccountRiskError("Delta account snapshot completeness is insufficient")
    orders, fills = snapshot.get("orders"), snapshot.get("fills")
    if not isinstance(orders, list) or not isinstance(fills, list):
        raise AccountRiskError("Delta account snapshot order/fill collections are malformed")
    component_times = snapshot.get("component_observed_at_ns")
    if not isinstance(component_times, dict):
        raise AccountRiskError("Delta account snapshot component timestamps are missing")
    order_time, fill_time = component_times.get("orders"), component_times.get("fills")
    for value in (order_time, fill_time, snapshot.get("observed_at_ns")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AccountRiskError("Delta account snapshot contains an invalid observation timestamp")

    order_snapshot = {
        "venue": "delta", "account_id": scope.provider_account_id,
        "source": "delta-v2-read-only-account-snapshot:orders",
        "complete": True, "snapshot_as_of_ns": order_time, "orders": orders,
    }
    fill_snapshot = {
        "venue": "delta", "account_id": scope.provider_account_id,
        "source": "delta-v2-read-only-account-snapshot:fills",
        "complete": True, "snapshot_as_of_ns": fill_time, "fills": fills,
    }
    reconciliation = reconcile_delta_submission(
        journal, reservation_id, account_id=scope.provider_account_id,
        order_snapshot=order_snapshot, fill_snapshot=fill_snapshot,
        now_ns=time.time_ns() if now_ns is None else now_ns,
        max_age_seconds=max_age_seconds,
        max_snapshot_skew_seconds=max_snapshot_skew_seconds,
    )
    if reconciliation.get("resolved") is not True:
        return {"settled": False, "reason": reconciliation.get("reason", "unresolved"), "reconciliation": reconciliation}
    status = reconciliation.get("state")
    terminal_status = _TERMINAL_STATUS.get(status)
    if terminal_status is None:
        return {
            "settled": False,
            "reason": "order remains non-terminal; reservation stays pending",
            "reconciliation": reconciliation,
        }

    matched_orders = [
        row for row in orders
        if isinstance(row, dict)
        and str(row.get("client_order_id", row.get("clientOrderId", ""))).strip() == reservation_id
    ]
    if len(matched_orders) != 1:
        raise AccountRiskError("Delta snapshot does not contain exactly one matching client order")
    order = matched_orders[0]
    if order.get("id") in (None, ""):
        raise AccountRiskError("terminal Delta order is missing provider order ID")
    order_state = str(order.get("state", order.get("status", ""))).strip().upper()
    if order_state not in _TERMINAL_STATUS:
        raise AccountRiskError("matching Delta order is not terminal in the complete snapshot")

    try:
        observed_at = datetime.fromtimestamp(
            snapshot["observed_at_ns"] / 1_000_000_000,
            tz=timezone.utc,
        ).isoformat()
    except (OverflowError, OSError, ValueError) as exc:
        raise AccountRiskError("Delta snapshot observation time cannot be represented") from exc
    evidence = AccountRiskReconciliationEvidence(
        scope=scope,
        reservation_id=reservation_id,
        client_order_id=reservation_id,
        source="DELTA_AUTHENTICATED_READ",
        exchange_order_id=str(order["id"]),
        terminal_status=terminal_status,
        observed_at=observed_at,
        snapshot_hash=_canonical_snapshot_hash(snapshot),
        identity_verified=True,
        orders_complete=True,
        fills_complete=True,
        positions_complete=True,
        open_order_absent=True,
    )
    settled = coordinator.settle_reservation(
        scope=scope,
        reservation_id=reservation_id,
        expected_revision=reconciled_state.revision,
        reconciled_state=reconciled_state,
        evidence=evidence,
    )
    return {
        "settled": settled,
        "terminal_status": terminal_status,
        "exchange_order_id": str(order["id"]),
        "snapshot_hash": evidence.snapshot_hash,
        "reconciliation": reconciliation,
    }
