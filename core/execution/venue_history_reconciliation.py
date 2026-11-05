"""Evidence-gated reconciliation of ambiguous order submissions.

This module consumes a caller-supplied, authoritative, complete venue order-
history snapshot. It does not perform network I/O and never resubmits orders.
Absence from history is not proof of rejection.
"""
from __future__ import annotations

import hashlib
import json
import time

from core.execution.order_ack import classify_ack
from core.execution.submission_journal import (
    ACKNOWLEDGED, CANCELLED, EXPIRED, FILLED, PARTIAL, REJECTED,
    UNKNOWN, SubmissionJournalError,
)

RESOLVABLE = {ACKNOWLEDGED, FILLED, PARTIAL, REJECTED, CANCELLED, EXPIRED}


class VenueHistoryEvidenceError(ValueError):
    """Snapshot is incomplete, stale, or lacks provenance."""


def _canonical_digest(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reconcile_submission(
    journal,
    client_order_id: str,
    *,
    venue: str,
    account_id: str,
    source: str,
    snapshot_as_of_ns: int,
    orders,
    complete: bool,
    max_age_seconds: float = 30.0,
    now_ns: int | None = None,
):
    """Resolve one journal row only from a fresh, complete history snapshot.

    Each matching venue record must uniquely identify the local client order
    ID. The snapshot's provenance/completeness are assertions made by the
    venue adapter; callers must only set complete=True when the endpoint
    covers completed/rejected/cancelled as well as currently open orders.
    """
    required = (venue, account_id, source, client_order_id)
    if any(not str(value or "").strip() for value in required):
        raise VenueHistoryEvidenceError("venue, account, source and client order ID are required")
    if not complete:
        raise VenueHistoryEvidenceError("venue history snapshot is not declared complete")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    now = time.time_ns() if now_ns is None else int(now_ns)
    as_of = int(snapshot_as_of_ns)
    age_ns = now - as_of
    if age_ns < 0 or age_ns > int(max_age_seconds * 1_000_000_000):
        raise VenueHistoryEvidenceError("venue history snapshot is stale or from the future")
    if not isinstance(orders, (list, tuple)):
        raise VenueHistoryEvidenceError("orders must be a list/tuple snapshot")
    if any(not isinstance(item, dict) for item in orders):
        raise VenueHistoryEvidenceError("every venue order record must be a mapping")

    matches = [
        item for item in orders
        if str(item.get("client_order_id", item.get("clientOrderId", ""))).strip()
        == str(client_order_id).strip()
    ]
    if len(matches) > 1:
        raise VenueHistoryEvidenceError("duplicate venue records match client order ID")
    if not matches:
        # A complete snapshot with no match still cannot prove non-submission:
        # delayed indexing, retention, or venue-specific history gaps exist.
        return {"resolved": False, "state": UNKNOWN, "reason": "no matching venue history record"}

    record = matches[0]
    verdict = classify_ack(record)
    if verdict.state not in RESOLVABLE:
        return {"resolved": False, "state": UNKNOWN, "reason": verdict.detail}

    row = journal.get(client_order_id)
    if row is None:
        raise SubmissionJournalError("submission reservation not found")
    digest = _canonical_digest({
        "venue": str(venue), "account_id": str(account_id),
        "source": str(source), "snapshot_as_of_ns": as_of,
        "client_order_id": str(client_order_id), "record": record,
    })
    detail = (
        f"venue_history:{venue}:{account_id}:{source}:"
        f"as_of_ns={as_of}:sha256={digest}:status={verdict.status_raw}"
    )
    journal.transition(client_order_id, verdict.state, detail)
    return {
        "resolved": True, "state": verdict.state,
        "client_order_id": str(client_order_id),
        "evidence_sha256": digest, "snapshot_as_of_ns": as_of,
    }
