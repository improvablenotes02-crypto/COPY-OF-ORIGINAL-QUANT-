"""Conservative fill-history corroboration for Delta order records.

This module never changes journal state. It aggregates uniquely identified
fills for one venue order and reports execution evidence only. A zero-fill
result is not evidence of rejection or proof that an order was never sent.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


class DeltaFillEvidenceError(ValueError):
    """Fill snapshot or its relationship to an order is unsafe to interpret."""


def _positive_decimal(value, field):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DeltaFillEvidenceError(f"{field} is not a valid decimal") from exc
    if not number.is_finite() or number <= 0:
        raise DeltaFillEvidenceError(f"{field} must be finite and positive")
    return number


def summarize_delta_order_fills(
    order,
    *,
    fills,
    venue: str,
    account_id: str,
    source: str,
    snapshot_as_of_ns: int,
    complete: bool,
):
    """Summarize fills for an order using order_id, never fuzzy matching.

    account_id is an operator/adapter-supplied scope assertion: Delta fill
    rows do not carry an account identifier. This function therefore does
    not independently authenticate that assertion.
    """
    if not isinstance(order, dict) or order.get("id") in (None, ""):
        raise DeltaFillEvidenceError("order must contain a venue order id")
    if not all(str(value or "").strip() for value in (venue, account_id, source)):
        raise DeltaFillEvidenceError("venue, account_id and source are required")
    if not complete:
        raise DeltaFillEvidenceError("fills snapshot is incomplete")
    if isinstance(snapshot_as_of_ns, bool) or not isinstance(snapshot_as_of_ns, int) or snapshot_as_of_ns <= 0:
        raise DeltaFillEvidenceError("snapshot_as_of_ns must be a positive integer")
    if not isinstance(fills, (list, tuple)) or any(not isinstance(row, dict) for row in fills):
        raise DeltaFillEvidenceError("fills must be a list of mappings")

    order_id = str(order["id"])
    product_id = order.get("product_id")
    matched = []
    seen_fill_ids = set()
    total = Decimal("0")
    for row in fills:
        if str(row.get("order_id", "")) != order_id:
            continue
        if product_id is not None and row.get("product_id") is not None:
            if str(row["product_id"]) != str(product_id):
                raise DeltaFillEvidenceError("matching order_id has conflicting product_id")
        fill_id = str(row.get("id", row.get("fill_id", ""))).strip()
        if not fill_id:
            raise DeltaFillEvidenceError("matching fill is missing a stable fill id")
        if fill_id in seen_fill_ids:
            raise DeltaFillEvidenceError("duplicate fill id in snapshot")
        seen_fill_ids.add(fill_id)
        quantity = _positive_decimal(row.get("size"), "fill size")
        total += quantity
        matched.append({"fill_id": fill_id, "size": str(quantity)})

    if not matched:
        return {
            "has_fill_evidence": False,
            "execution_state": "NO_FILL_EVIDENCE",
            "filled_size": "0",
            "fill_count": 0,
            "order_id": order_id,
            "venue": str(venue),
            "account_id": str(account_id),
            "source": str(source),
            "snapshot_as_of_ns": snapshot_as_of_ns,
        }

    order_size = _positive_decimal(order.get("size"), "order size")
    if total > order_size:
        raise DeltaFillEvidenceError("aggregated fill quantity exceeds order size")
    state = "FILLED" if total == order_size else "PARTIAL"
    return {
        "has_fill_evidence": True,
        "execution_state": state,
        "filled_size": str(total),
        "order_size": str(order_size),
        "fill_count": len(matched),
        "fills": matched,
        "order_id": order_id,
        "venue": str(venue),
        "account_id": str(account_id),
        "source": str(source),
        "snapshot_as_of_ns": snapshot_as_of_ns,
    }
