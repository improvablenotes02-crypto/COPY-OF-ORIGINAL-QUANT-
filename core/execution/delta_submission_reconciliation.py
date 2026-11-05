"""Two-source, fail-closed Delta submission reconciliation.

Order history and fills are independent, non-atomic observations. This module
combines them conservatively and is the only Phase 266 path that may transition
the durable submission journal. It never performs network I/O or resubmits.
"""
from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal, InvalidOperation

from core.execution.delta_fill_reconciliation import (
    DeltaFillEvidenceError,
    summarize_delta_order_fills,
)
from core.execution.order_ack import (
    ACKNOWLEDGED, CANCELLED, EXPIRED, FILLED, PARTIAL, REJECTED, UNKNOWN,
    classify_ack,
)
from core.execution.submission_journal import SubmissionJournalError


class DeltaSubmissionReconciliationError(ValueError):
    """The two-source evidence is incomplete, stale, or contradictory."""


_RESOLVABLE = {ACKNOWLEDGED, FILLED, PARTIAL, REJECTED, CANCELLED, EXPIRED}


def _digest(value):
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DeltaSubmissionReconciliationError(
            "evidence is not canonical JSON"
        ) from exc
    return hashlib.sha256(payload).hexdigest()


def _snapshot_age(snapshot, *, now_ns, max_age_ns, label):
    if not isinstance(snapshot, dict):
        raise DeltaSubmissionReconciliationError(f"{label} snapshot must be a mapping")
    if snapshot.get("venue") != "delta":
        raise DeltaSubmissionReconciliationError(f"{label} snapshot venue mismatch")
    if snapshot.get("complete") is not True:
        raise DeltaSubmissionReconciliationError(f"{label} snapshot is incomplete")
    stamp = snapshot.get("snapshot_as_of_ns")
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
        raise DeltaSubmissionReconciliationError(f"{label} snapshot timestamp is invalid")
    age = now_ns - stamp
    if age < 0 or age > max_age_ns:
        raise DeltaSubmissionReconciliationError(f"{label} snapshot is stale or from the future")
    if not str(snapshot.get("source") or "").strip():
        raise DeltaSubmissionReconciliationError(f"{label} snapshot source is missing")
    return stamp



def _validate_explicit_scope(record, *, account_id, venue, label):
    """Reject contradictory scope fields while allowing providers to omit them."""
    if not isinstance(record, dict):
        raise DeltaSubmissionReconciliationError(f"{label} must be a mapping")
    for field in ("account_id", "accountId"):
        value = record.get(field)
        if value not in (None, "") and str(value).strip() != str(account_id):
            raise DeltaSubmissionReconciliationError(f"{label} account scope mismatch")
    value = record.get("venue")
    if value not in (None, "") and str(value).strip().lower() != str(venue).lower():
        raise DeltaSubmissionReconciliationError(f"{label} venue scope mismatch")


def reconcile_delta_submission(
    journal,
    client_order_id: str,
    *,
    account_id: str,
    order_snapshot,
    fill_snapshot,
    max_age_seconds: float = 30.0,
    max_snapshot_skew_seconds: float = 15.0,
    now_ns: int | None = None,
):
    """Reconcile one reservation using complete Delta order and fill snapshots.

    Exact client_order_id selects one order; exact venue order_id selects fills.
    Account scope is a caller assertion because Delta fill rows do not expose
    account_id. Missing fills never imply rejection. Contradictory evidence
    returns unresolved without mutating the journal.
    """
    key = str(client_order_id or "").strip()
    account = str(account_id or "").strip()
    if not key or not account:
        raise DeltaSubmissionReconciliationError("client_order_id and account_id are required")
    if max_age_seconds <= 0 or max_snapshot_skew_seconds < 0:
        raise ValueError("snapshot age must be positive and skew non-negative")
    now = time.time_ns() if now_ns is None else now_ns
    if isinstance(now, bool) or not isinstance(now, int) or now <= 0:
        raise ValueError("now_ns must be a positive integer")
    max_age_ns = int(max_age_seconds * 1_000_000_000)
    _validate_explicit_scope(order_snapshot, account_id=account, venue="delta", label="order snapshot")
    _validate_explicit_scope(fill_snapshot, account_id=account, venue="delta", label="fill snapshot")
    order_stamp = _snapshot_age(
        order_snapshot, now_ns=now, max_age_ns=max_age_ns, label="order-history"
    )
    fill_stamp = _snapshot_age(
        fill_snapshot, now_ns=now, max_age_ns=max_age_ns, label="fill-history"
    )
    if abs(order_stamp - fill_stamp) > int(max_snapshot_skew_seconds * 1_000_000_000):
        raise DeltaSubmissionReconciliationError("order and fill snapshots exceed allowed time skew")
    orders = order_snapshot.get("orders")
    fills = fill_snapshot.get("fills")
    if not isinstance(orders, (list, tuple)) or any(not isinstance(x, dict) for x in orders):
        raise DeltaSubmissionReconciliationError("order-history records are malformed")
    if not isinstance(fills, (list, tuple)) or any(not isinstance(x, dict) for x in fills):
        raise DeltaSubmissionReconciliationError("fill-history records are malformed")

    matches = [
        row for row in orders
        if str(row.get("client_order_id", row.get("clientOrderId", ""))).strip() == key
    ]
    if len(matches) > 1:
        raise DeltaSubmissionReconciliationError("multiple order records match client_order_id")
    if not matches:
        return {
            "resolved": False, "state": UNKNOWN,
            "reason": "no matching order record; absence is not proof of rejection",
        }

    order = matches[0]
    _validate_explicit_scope(order, account_id=account, venue="delta", label="matched order")
    if order.get("id") in (None, ""):
        raise DeltaSubmissionReconciliationError("matched order is missing venue order id")
    try:
        fill_evidence = summarize_delta_order_fills(
            order,
            fills=fills,
            venue="delta",
            account_id=account,
            source=str(fill_snapshot["source"]),
            snapshot_as_of_ns=fill_stamp,
            complete=True,
        )
    except DeltaFillEvidenceError as exc:
        raise DeltaSubmissionReconciliationError(str(exc)) from exc

    matching_fill_rows = [row for row in fills if str(row.get("order_id", "")) == str(order["id"])]
    for fill_row in matching_fill_rows:
        _validate_explicit_scope(fill_row, account_id=account, venue="delta", label="matched fill")
    verdict = classify_ack(order)
    order_state = verdict.state
    has_fills = fill_evidence["has_fill_evidence"]
    fill_state = fill_evidence["execution_state"]

    if has_fills:
        # If the order endpoint publishes a cumulative quantity, it must
        # agree with the independently aggregated fill records.
        if verdict.filled_qty is not None:
            try:
                reported = Decimal(str(verdict.filled_qty))
                observed = Decimal(fill_evidence["filled_size"])
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise DeltaSubmissionReconciliationError(
                    "order filled quantity is unreadable"
                ) from exc
            if reported != observed:
                return {
                    "resolved": False, "state": UNKNOWN,
                    "reason": "order cumulative quantity conflicts with fill aggregation",
                    "fill_evidence": fill_evidence,
                }
        if order_state == REJECTED:
            return {
                "resolved": False, "state": UNKNOWN,
                "reason": "rejected order record conflicts with observed fills",
                "fill_evidence": fill_evidence,
            }
        if order_state in (FILLED, PARTIAL) and order_state != fill_state:
            return {
                "resolved": False, "state": UNKNOWN,
                "reason": "order status conflicts with aggregated fill quantity",
                "fill_evidence": fill_evidence,
            }
        if order_state in (CANCELLED, EXPIRED) and fill_state == FILLED:
            return {
                "resolved": False, "state": UNKNOWN,
                "reason": "cancelled/expired order conflicts with full fill quantity",
                "fill_evidence": fill_evidence,
            }
        # A cancellation/expiry may legitimately follow a partial execution.
        # Keep the terminal order lifecycle state while retaining fill detail.
        final_state = order_state if order_state in (CANCELLED, EXPIRED) else fill_state
    else:
        if order_state in (FILLED, PARTIAL):
            return {
                "resolved": False, "state": UNKNOWN,
                "reason": "order claims execution but complete fills snapshot has no corroborating fills",
                "fill_evidence": fill_evidence,
            }
        if order_state in (CANCELLED, EXPIRED):
            return {
                "resolved": False, "state": UNKNOWN,
                "reason": "cancelled/expired order has no fill corroboration; prior partial execution cannot be excluded",
                "fill_evidence": fill_evidence,
            }
        if order_state not in (ACKNOWLEDGED, REJECTED):
            return {
                "resolved": False, "state": UNKNOWN,
                "reason": verdict.detail or "order status is unresolved",
                "fill_evidence": fill_evidence,
            }
        final_state = order_state

    if final_state not in _RESOLVABLE:
        return {"resolved": False, "state": UNKNOWN, "reason": "unsupported reconciliation state"}

    reservation = journal.get(key)
    if reservation is None:
        raise SubmissionJournalError("submission reservation not found")
    evidence = {
        "evidence_schema": "quantengine.delta-dual-history.v2",
        "reservation_payload_sha256": reservation["payload_sha256"],
        "venue": "delta",
        "account_id": account,
        "client_order_id": key,
        "order_source": order_snapshot["source"],
        "order_snapshot_as_of_ns": order_stamp,
        "order_snapshot_complete": True,
        "order_snapshot": order_snapshot,
        "fill_source": fill_snapshot["source"],
        "fill_snapshot_as_of_ns": fill_stamp,
        "fill_snapshot_complete": True,
        "fill_snapshot": fill_snapshot,
        "order": order,
        "fill_evidence": fill_evidence,
        "resolved_state": final_state,
    }
    digest = _digest(evidence)
    detail = (
        f"delta_dual_history:{account}:order_as_of_ns={order_stamp}:"
        f"fills_as_of_ns={fill_stamp}:sha256={digest}:state={final_state}"
    )
    journal.transition(key, final_state, detail, evidence_sha256=digest)
    return {
        "resolved": True,
        "state": final_state,
        "client_order_id": key,
        "account_id": account,
        "evidence_sha256": digest,
        "order_snapshot_as_of_ns": order_stamp,
        "fill_snapshot_as_of_ns": fill_stamp,
        "fill_evidence": fill_evidence,
    }
