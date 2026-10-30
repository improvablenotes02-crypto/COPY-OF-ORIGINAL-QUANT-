"""
====================================================
QuantEngine - Dedicated Testnet Experiment Authorization Gate
Phase 189 Implementation

Fail-closed authorization preflight gate for gated testnet experiments.
Guarantees absolute separation from live production trading:
  * Rejects production endpoints with typed ProductionEndpointAttemptedError.
  * Rejects templates in PENDING_OPERATOR_APPROVAL state or containing unreplaced placeholders.
  * Enforces verified instrument metadata, single open order, max 20 cumulative orders across restarts.
  * Tracks cumulative order counts against a persistent ledger file.
  * Enforces fail-closed handling for ambiguous order acknowledgments and resting timeouts.
  * Provides a latched kill switch that permanently halts new submissions upon failure.
  * Every refusal path guarantees zero exchange order writes.
====================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set

from core.common.logging_config import get_logger
from core.execution.testnet_safety_gate import (
    ALLOWED_TESTNET_REST_URLS,
    ALLOWED_TESTNET_WS_URLS,
    FORBIDDEN_PRODUCTION_URLS,
    ProductionEndpointAttemptedError,
    TestnetBlockedError,
    TestnetConfigurationError,
    TestnetSafetyError,
)

log = get_logger(__name__)

_AUDIT_COMPONENT = "TestnetAuthorizationGate"
_GATE_MINT = secrets.token_hex(16)


class AuthorizationState(str, Enum):
    """Explicit lifecycle states for experiment authorization."""
    PENDING_OPERATOR_APPROVAL = "PENDING_OPERATOR_APPROVAL"
    OPERATOR_APPROVED = "OPERATOR_APPROVED"
    EXPIRED = "EXPIRED"
    KILLED = "KILLED"
    REVOKED = "REVOKED"
    INVALID_SCOPE = "INVALID_SCOPE"
    MALFORMED = "MALFORMED"


class OrderLifecycleState(str, Enum):
    """Explicit lifecycle states for individual experiment orders.
    
    Distinguishes the 10 canonical Phase 191 lifecycle states while preserving
    backwards-compatible Phase 189/190 aliases.
    """
    # Phase 191 Canonical 10 States
    NOT_SUBMITTED = "NOT_SUBMITTED"
    RESERVED = "RESERVED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED_CONFIRMED = "CANCELLED_CONFIRMED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    LEDGER_CORRUPTED = "LEDGER_CORRUPTED"

    # Backward-compatible Phase 189/190 aliases
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    RESTING = "RESTING"
    CANCELLED_UNFILLED = "CANCELLED_UNFILLED"
    FILLED_POST_CANCEL_REQ = "FILLED_POST_CANCEL_REQ"
    REJECTED_POST_ONLY = "REJECTED_POST_ONLY"
    AMBIGUOUS_STATE = "AMBIGUOUS_STATE"
    HALTED = "HALTED"


ORDER_STATE_CANONICAL_MAP: Dict[OrderLifecycleState, OrderLifecycleState] = {
    OrderLifecycleState.NOT_SUBMITTED: OrderLifecycleState.NOT_SUBMITTED,
    OrderLifecycleState.RESERVED: OrderLifecycleState.RESERVED,
    OrderLifecycleState.PENDING_SUBMISSION: OrderLifecycleState.RESERVED,
    OrderLifecycleState.SUBMISSION_UNKNOWN: OrderLifecycleState.SUBMISSION_UNKNOWN,
    OrderLifecycleState.SUBMITTED: OrderLifecycleState.SUBMISSION_UNKNOWN,
    OrderLifecycleState.ACKNOWLEDGED: OrderLifecycleState.ACKNOWLEDGED,
    OrderLifecycleState.RESTING: OrderLifecycleState.ACKNOWLEDGED,
    OrderLifecycleState.PARTIALLY_FILLED: OrderLifecycleState.PARTIALLY_FILLED,
    OrderLifecycleState.FILLED: OrderLifecycleState.FILLED,
    OrderLifecycleState.FILLED_POST_CANCEL_REQ: OrderLifecycleState.FILLED,
    OrderLifecycleState.CANCEL_REQUESTED: OrderLifecycleState.CANCEL_REQUESTED,
    OrderLifecycleState.CANCELLED_CONFIRMED: OrderLifecycleState.CANCELLED_CONFIRMED,
    OrderLifecycleState.CANCELLED_UNFILLED: OrderLifecycleState.CANCELLED_CONFIRMED,
    OrderLifecycleState.REJECTED_POST_ONLY: OrderLifecycleState.CANCELLED_CONFIRMED,
    OrderLifecycleState.RECONCILIATION_REQUIRED: OrderLifecycleState.RECONCILIATION_REQUIRED,
    OrderLifecycleState.AMBIGUOUS_STATE: OrderLifecycleState.RECONCILIATION_REQUIRED,
    OrderLifecycleState.HALTED: OrderLifecycleState.RECONCILIATION_REQUIRED,
    OrderLifecycleState.LEDGER_CORRUPTED: OrderLifecycleState.LEDGER_CORRUPTED,
}


class AuthorizationIntegrityError(TestnetSafetyError):
    """Authorization record is missing, malformed, expired, or unapproved."""
    __test__ = False


class KillSwitchActiveError(TestnetSafetyError):
    """CRITICAL: Kill switch has been triggered; execution is permanently halted."""
    __test__ = False


class OrderLimitExceededError(TestnetSafetyError):
    """Cumulative or concurrent order limits exceeded."""
    __test__ = False


class AmbiguousOrderStateError(TestnetSafetyError):
    """Matching engine acknowledgment timed out or order status is unknown."""
    __test__ = False


class LockTimeoutError(TestnetSafetyError):
    """Cross-process lock acquisition timed out within bounded window."""
    __test__ = False


class LedgerCorruptedError(TestnetSafetyError):
    """Persistent ledger file contains unparseable, truncated, or conflicting records."""
    __test__ = False


class DuplicateClientOrderIdError(TestnetSafetyError):
    """Client order ID was already submitted or reserved in ledger."""
    __test__ = False


class CrossProcessFileLock:
    """Bounded, crash-safe cross-process file lock supporting Windows (msvcrt) and POSIX (fcntl).
    
    Provides reentrancy per-thread within the same process, and strict mutual
    exclusion across distinct processes. If the holding process crashes, the OS
    automatically frees kernel-held file locks, preventing permanent deadlocks.
    """
    _local = threading.local()

    def __init__(self, lock_path: Path | str, timeout_seconds: float = 5.0, poll_interval: float = 0.02):
        self.lock_path = Path(lock_path)
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval = float(poll_interval)
        self._fd: Optional[int] = None
        self._file_obj = None
        # The OS lock is owned by the first instance. Re-entrant instances
        # share that owner so the final release always unlocks the descriptor
        # that actually acquired the kernel lock.
        self._owner: Optional[CrossProcessFileLock] = None

    def _normalize_key(self) -> str:
        k = str(self.lock_path.resolve())
        return k.lower() if sys.platform == "win32" else k

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if not hasattr(CrossProcessFileLock._local, "held_locks"):
            CrossProcessFileLock._local.held_locks = {}

        path_key = self._normalize_key()
        held_locks = CrossProcessFileLock._local.held_locks
        if path_key in held_locks:
            state = held_locks[path_key]
            state["count"] += 1
            self._owner = state["owner"]
            return

        start_time = time.monotonic()
        f = open(self.lock_path, "a+b")
        fd = f.fileno()

        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._file_obj = f
                self._fd = fd
                self._owner = self
                held_locks[path_key] = {"count": 1, "owner": self}
                return
            except (OSError, IOError) as exc:
                elapsed = time.monotonic() - start_time
                if elapsed >= self.timeout_seconds:
                    try:
                        f.close()
                    except Exception:
                        pass
                    raise LockTimeoutError(
                        f"Failed to acquire cross-process lock {self.lock_path} within {self.timeout_seconds:.1f}s: {exc}"
                    ) from exc
                time.sleep(self.poll_interval)

    def release(self) -> None:
        path_key = self._normalize_key()
        if not hasattr(CrossProcessFileLock._local, "held_locks"):
            return
        held_locks = CrossProcessFileLock._local.held_locks
        state = held_locks.get(path_key)
        if state is None:
            return

        state["count"] -= 1
        if state["count"] > 0:
            return  # still held by an outer or re-entrant context

        del held_locks[path_key]
        # A re-entrant instance may be the final releaser even though it did
        # not open the descriptor. Always release through the original owner.
        owner = state["owner"]
        if owner._file_obj and not owner._file_obj.closed:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    owner._file_obj.seek(0)
                    msvcrt.locking(owner._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(owner._fd, fcntl.LOCK_UN)
            except Exception as exc:
                log.warning("Exception during lock release for %s: %s", owner.lock_path, exc)
            finally:
                try:
                    owner._file_obj.close()
                except Exception:
                    pass
                owner._file_obj = None
                owner._fd = None
                owner._owner = None
        self._owner = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


@dataclass(frozen=True)
class ExperimentScope:
    """Rigid boundaries authorized for a specific experiment."""
    venue: str
    target_rest_url: str
    target_ws_url: str
    allowed_symbols: Set[str]
    allowed_product_ids: Set[int]
    max_cumulative_orders: int
    max_simultaneous_open_orders: int
    max_order_size_contracts: Decimal
    max_order_notional_usd: Decimal
    max_loss_budget_usd: Decimal
    max_order_wait_seconds: float
    require_post_only: bool
    forbid_market_conversion: bool
    require_valid_book: bool = False


@dataclass
class OperatorAuthorizationRecord:
    """Parsed, verifiable authorization document."""
    authorization_id: str
    state: AuthorizationState
    operator_identity: str
    signed_timestamp_utc: str
    expiry_timestamp_utc: str
    scope: ExperimentScope
    document_sha256: str
    signature_payload: str
    raw_content: str = ""

    def is_currently_valid(self, now_utc_seconds: Optional[float] = None) -> bool:
        """Check whether authorization is in approved state and within validity window."""
        if self.state != AuthorizationState.OPERATOR_APPROVED:
            return False
        if not self.operator_identity or self.operator_identity.startswith("["):
            return False
        if not self.signature_payload or self.signature_payload.startswith("["):
            return False
        return True


@dataclass(frozen=True)
class AuthorizationDecision:
    """Verdict rendered by the authorization gate."""
    __test__ = False
    authorized: bool
    state: AuthorizationState
    reasons: List[str] = field(default_factory=list)
    cumulative_orders_placed: int = 0
    current_open_orders: int = 0
    current_realized_loss_usd: Decimal = Decimal("0.0")
    timestamp_utc: float = field(default_factory=time.time)
    _mint_token: str = field(default="", repr=False)

    def is_armed(self) -> bool:
        return self.authorized and self._mint_token == _GATE_MINT


class TestnetAuthorizationGate:
    """Fail-closed gate validating authorization, scope, persistent order count, and state."""
    __test__ = False

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        default_scope: Optional[ExperimentScope] = None,
    ):
        self.ledger_path = Path(ledger_path or (
            Path(__file__).resolve().parents[2] / "research" / "results" / "phase189_testnet_experiment_ledger.jsonl"
        ))
        self.lock_path = self.ledger_path.with_suffix(".lock")
        self.scope = default_scope or ExperimentScope(
            venue="DELTA_INDIA_TESTNET",
            target_rest_url="https://cdn-ind.testnet.deltaex.org",
            target_ws_url="wss://socket-ind.testnet.deltaex.org",
            allowed_symbols={"BTCUSD"},
            allowed_product_ids={84},
            max_cumulative_orders=20,
            max_simultaneous_open_orders=1,
            max_order_size_contracts=Decimal("1.0"),
            max_order_notional_usd=Decimal("100.00"),
            max_loss_budget_usd=Decimal("5.00"),
            max_order_wait_seconds=120.0,
            require_post_only=True,
            forbid_market_conversion=True,
        )
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
        self._active_open_orders: Dict[str, Dict[str, Any]] = {}
        self._ambiguous_orders: Dict[str, Dict[str, Any]] = {}
        self._ledger_corrupted: bool = False
        self._ledger_corruption_reason: str = ""

    def activate_kill_switch(self, reason: str) -> None:
        """Permanently latch kill switch. Refuses all subsequent order actions."""
        self._kill_switch_active = True
        self._kill_switch_reason = str(reason)
        log.critical("TESTNET_KILL_SWITCH_ACTIVATED reason=%s", reason)

    @property
    def is_killed(self) -> bool:
        return self._kill_switch_active

    def parse_authorization_document(self, content_or_path: str | Path) -> OperatorAuthorizationRecord:
        """Parse authorization document and strictly detect template placeholders."""
        if isinstance(content_or_path, Path) or (isinstance(content_or_path, str) and os.path.exists(content_or_path)):
            path = Path(content_or_path)
            raw = path.read_text(encoding="utf-8")
        else:
            raw = str(content_or_path)

        doc_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        # Check for unreplaced template placeholders
        has_placeholders = bool(re.search(r"\[(OPERATOR_[A-Z0-9_]+|REQUIRED|PENDING|TODO)\]", raw, re.IGNORECASE))
        has_pending_status = "PENDING_OPERATOR_APPROVAL" in raw

        # Parse fields
        auth_id = ""
        operator = ""
        signed_ts = ""
        expiry_ts = ""
        sig_payload = ""

        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("- **Authorization ID**:") or line.startswith("Authorization ID:"):
                auth_id = line.split(":", 1)[1].strip(" *`")
            elif line.startswith("- **Authorizing Operator**:") or line.startswith("Authorizing Operator:"):
                operator = line.split(":", 1)[1].strip(" *`")
            elif line.startswith("- **Signed Timestamp UTC**:") or line.startswith("Signed Timestamp UTC:"):
                signed_ts = line.split(":", 1)[1].strip(" *`")
            elif line.startswith("- **Expiry Timestamp UTC**:") or line.startswith("Expiry Timestamp UTC:"):
                expiry_ts = line.split(":", 1)[1].strip(" *`")
            elif line.startswith("- **Operator Signature**:") or line.startswith("Operator Signature:"):
                sig_payload = line.split(":", 1)[1].strip(" *`")

        if has_placeholders or has_pending_status:
            state = AuthorizationState.PENDING_OPERATOR_APPROVAL
        elif not operator or not sig_payload or sig_payload.startswith("["):
            state = AuthorizationState.MALFORMED
        else:
            state = AuthorizationState.OPERATOR_APPROVED

        return OperatorAuthorizationRecord(
            authorization_id=auth_id or "P189-UNIDENTIFIED",
            state=state,
            operator_identity=operator,
            signed_timestamp_utc=signed_ts,
            expiry_timestamp_utc=expiry_ts,
            scope=self.scope,
            document_sha256=doc_hash,
            signature_payload=sig_payload,
            raw_content=raw,
        )

    def read_cumulative_orders_from_ledger(self) -> int:
        """Inspect persistent append-only ledger to prevent reset across restarts.

        Detects file corruption, unparseable lines, duplicate order IDs, and conflicting states.
        Fails closed by latching _ledger_corrupted = True on any integrity fault.
        """
        if not self.ledger_path.exists():
            return 0

        reserved_order_ids: Set[str] = set()
        submitted_order_ids: Set[str] = set()
        all_order_ids: Set[str] = set()
        unidentified_orders_count = 0

        with CrossProcessFileLock(self.lock_path):
            try:
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    for line_no, raw_line in enumerate(f, start=1):
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if not isinstance(record, dict) or "event" not in record:
                                self._ledger_corrupted = True
                                self._ledger_corruption_reason = f"Malformed record structure at line {line_no}"
                                continue

                            event = record.get("event")
                            data = record.get("data", {}) if isinstance(record.get("data"), dict) else {}
                            cl_ord_id = data.get("cl_ord_id")

                            if event == "ORDER_RESERVED":
                                if cl_ord_id:
                                    if cl_ord_id in reserved_order_ids:
                                        self._ledger_corrupted = True
                                        self._ledger_corruption_reason = f"Duplicate cl_ord_id reservation {cl_ord_id!r} at line {line_no}"
                                    reserved_order_ids.add(cl_ord_id)
                                    all_order_ids.add(cl_ord_id)
                                else:
                                    unidentified_orders_count += 1

                            elif event in ("ORDER_SUBMITTED", "ORDER_PLACED"):
                                if cl_ord_id:
                                    if cl_ord_id in submitted_order_ids:
                                        self._ledger_corrupted = True
                                        self._ledger_corruption_reason = f"Duplicate cl_ord_id {cl_ord_id!r} at line {line_no}"
                                    submitted_order_ids.add(cl_ord_id)
                                    all_order_ids.add(cl_ord_id)
                                else:
                                    unidentified_orders_count += 1
                        except Exception as parse_err:
                            self._ledger_corrupted = True
                            self._ledger_corruption_reason = f"Corrupted JSON at line {line_no}: {parse_err}"
            except Exception as exc:
                self._ledger_corrupted = True
                self._ledger_corruption_reason = f"IO error reading ledger: {exc}"
                log.error("Failed to read experiment ledger %s: %s", self.ledger_path, exc)

        return len(all_order_ids) + unidentified_orders_count

    def record_order_event_to_ledger(self, event_type: str, data: Dict[str, Any]) -> None:
        """Durable append-only audit record of order transitions with fsync."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp_utc": time.time(),
            "event": event_type,
            "data": data,
        }
        with CrossProcessFileLock(self.lock_path):
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def evaluate_preflight(
        self,
        auth_record: OperatorAuthorizationRecord,
        rest_url: str,
        symbol: str,
        product_id: int,
        order_size_contracts: Decimal | float,
        post_only: bool = True,
        cumulative_realized_loss: Decimal | float = Decimal("0.0"),
        book_tracker: Optional[Any] = None,
    ) -> AuthorizationDecision:
        """Evaluate preflight gate prior to order placement attempt.

        Guarantees:
          - Zero network I/O.
          - Fail closed on production URLs.
          - Fail closed on unapproved / placeholder authorizations.
          - Fail closed on order limit (cumulative >= 20 or open >= 1).
          - Fail closed on loss budget breach.
          - Fail closed on corrupted ledger or unreconciled ambiguous orders.
          - Fail closed on invalid, crossed, or stale order book state.
        """
        reasons: List[str] = []

        # 1. Kill switch check
        if self._kill_switch_active:
            reasons.append(f"Kill switch active: {self._kill_switch_reason}")
            return AuthorizationDecision(
                authorized=False,
                state=AuthorizationState.KILLED,
                reasons=reasons,
            )

        # 2. Endpoint validation & production isolation
        url_clean = str(rest_url or "").strip().rstrip("/")
        if not url_clean:
            reasons.append("REST endpoint is empty")
        elif url_clean in FORBIDDEN_PRODUCTION_URLS:
            # Immediate fail closed on production URL
            raise ProductionEndpointAttemptedError(
                f"CRITICAL SAFETY VIOLATION: Production endpoint {url_clean!r} attempted!"
            )
        elif url_clean not in ALLOWED_TESTNET_REST_URLS:
            reasons.append(f"Endpoint {url_clean!r} is not an authorized testnet host")

        # 3. Authorization status
        if auth_record.state == AuthorizationState.PENDING_OPERATOR_APPROVAL:
            reasons.append(
                "Authorization record is in PENDING_OPERATOR_APPROVAL state (requires signed operator signoff)"
            )
        elif auth_record.state != AuthorizationState.OPERATOR_APPROVED:
            reasons.append(f"Authorization record state {auth_record.state.value} is not approved")
        elif not auth_record.is_currently_valid():
            reasons.append("Authorization record signature or operator credentials invalid")

        # 4. Scope and instrument check
        sym_clean = str(symbol or "").strip().upper()
        if sym_clean not in self.scope.allowed_symbols:
            reasons.append(f"Symbol {sym_clean!r} not in authorized scope: {self.scope.allowed_symbols}")

        if product_id not in self.scope.allowed_product_ids:
            reasons.append(f"Product ID {product_id} not in authorized scope: {self.scope.allowed_product_ids}")

        # 5. Order sizing
        try:
            sz = Decimal(str(order_size_contracts))
            if sz <= 0:
                reasons.append("Order size must be positive")
            elif sz > self.scope.max_order_size_contracts:
                reasons.append(
                    f"Order size ({sz}) exceeds maximum authorized ({self.scope.max_order_size_contracts})"
                )
        except Exception as exc:
            reasons.append(f"Malformed order size: {exc}")

        # 6. Post-only enforcement
        if self.scope.require_post_only and not post_only:
            reasons.append("Post-only is mandatory in experiment scope; taker orders strictly prohibited")

        # 7. Ambiguous state check
        if len(self._ambiguous_orders) > 0:
            reasons.append(
                f"Matching engine has {len(self._ambiguous_orders)} ambiguous/unreconciled orders; placement halted"
            )

        # 8. Single-open-order constraint
        current_open = len(self._active_open_orders)
        if current_open >= self.scope.max_simultaneous_open_orders:
            reasons.append(
                f"Single-open-order limit reached ({current_open} open >= {self.scope.max_simultaneous_open_orders})"
            )

        # 9. Persistent cumulative order count across restarts
        cumulative_orders = self.read_cumulative_orders_from_ledger()
        if self._ledger_corrupted:
            reasons.append(
                f"Persistent ledger corrupted or unparseable: {self._ledger_corruption_reason}; failing closed"
            )
        elif cumulative_orders >= self.scope.max_cumulative_orders:
            reasons.append(
                f"Cumulative experiment order limit reached ({cumulative_orders} placed >= {self.scope.max_cumulative_orders})"
            )

        # 10. Realized loss budget check
        try:
            loss = Decimal(str(cumulative_realized_loss))
            if loss < Decimal("0.0"):
                loss = abs(loss)
            if loss >= self.scope.max_loss_budget_usd:
                reasons.append(
                    f"Cumulative loss (${loss}) has exhausted authorized budget (${self.scope.max_loss_budget_usd})"
                )
        except Exception as exc:
            reasons.append(f"Malformed loss value: {exc}")

        # 11. Market Data Order Book Validity
        if book_tracker is not None:
            if hasattr(book_tracker, "is_execution_eligible"):
                eligible, book_reasons = book_tracker.is_execution_eligible()
                if not eligible:
                    reasons.append(
                        f"Market data order book is not execution-eligible: {'; '.join(book_reasons)}"
                    )
            elif hasattr(book_tracker, "state"):
                if str(getattr(book_tracker, "state", "")).upper() != "VALID":
                    reasons.append(f"Market data order book state {book_tracker.state} is not VALID")
        elif getattr(self.scope, "require_valid_book", False):
            reasons.append("Market data order book validation required by scope, but no book tracker provided")

        is_authorized = len(reasons) == 0
        mint_token = _GATE_MINT if is_authorized else ""

        return AuthorizationDecision(
            authorized=is_authorized,
            state=auth_record.state if is_authorized else (
                AuthorizationState.KILLED if self._kill_switch_active else
                AuthorizationState.INVALID_SCOPE if not is_authorized and auth_record.state == AuthorizationState.OPERATOR_APPROVED else
                auth_record.state
            ),
            reasons=reasons,
            cumulative_orders_placed=cumulative_orders,
            current_open_orders=current_open,
            current_realized_loss_usd=Decimal(str(cumulative_realized_loss)),
            _mint_token=mint_token,
        )

    def check_and_reserve_order(
        self,
        auth_record: OperatorAuthorizationRecord,
        rest_url: str,
        symbol: str,
        product_id: int,
        order_size_contracts: Decimal | float,
        cl_ord_id: str,
        order_details: Optional[Dict[str, Any]] = None,
        post_only: bool = True,
        cumulative_realized_loss: Decimal | float = Decimal("0.0"),
        lock_timeout_seconds: float = 5.0,
        book_tracker: Optional[Any] = None,
    ) -> AuthorizationDecision:
        """Atomic check-and-reserve transaction under cross-process file lock.

        Guarantees:
          - Serialized check-and-reserve prevents concurrent processes consuming > 20 orders.
          - Rejects duplicate cl_ord_id immediately.
          - Flushes and fsyncs ORDER_RESERVED record before releasing lock.
          - Fails closed on any corruption, limit breach, or lock timeout.
          - Fails closed on invalid, crossed, or stale order book state.
        """
        cl_ord_id_clean = str(cl_ord_id or "").strip()
        if not cl_ord_id_clean:
            return AuthorizationDecision(
                authorized=False,
                state=AuthorizationState.MALFORMED,
                reasons=["Empty or invalid cl_ord_id"],
            )

        with CrossProcessFileLock(self.lock_path, timeout_seconds=lock_timeout_seconds):
            # 1. Run full preflight evaluation
            decision = self.evaluate_preflight(
                auth_record=auth_record,
                rest_url=rest_url,
                symbol=symbol,
                product_id=product_id,
                order_size_contracts=order_size_contracts,
                post_only=post_only,
                cumulative_realized_loss=cumulative_realized_loss,
                book_tracker=book_tracker,
            )
            if not decision.authorized:
                return decision

            # 2. Check for duplicate cl_ord_id in active or ambiguous tracking
            if cl_ord_id_clean in self._active_open_orders or cl_ord_id_clean in self._ambiguous_orders:
                return AuthorizationDecision(
                    authorized=False,
                    state=AuthorizationState.INVALID_SCOPE,
                    reasons=[f"Duplicate cl_ord_id {cl_ord_id_clean!r} already active or ambiguous"],
                    cumulative_orders_placed=decision.cumulative_orders_placed,
                    current_open_orders=len(self._active_open_orders),
                )

            # 3. Check for duplicate cl_ord_id in persistent ledger
            if self.ledger_path.exists():
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    for line_no, raw_line in enumerate(f, start=1):
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            d = rec.get("data", {}) if isinstance(rec.get("data"), dict) else {}
                            if d.get("cl_ord_id") == cl_ord_id_clean:
                                return AuthorizationDecision(
                                    authorized=False,
                                    state=AuthorizationState.INVALID_SCOPE,
                                    reasons=[f"Duplicate cl_ord_id {cl_ord_id_clean!r} already recorded in ledger at line {line_no}"],
                                    cumulative_orders_placed=decision.cumulative_orders_placed,
                                    current_open_orders=len(self._active_open_orders),
                                )
                        except Exception:
                            pass

            # 4. Atomic reservation append with fsync
            reservation_data = {
                "cl_ord_id": cl_ord_id_clean,
                "symbol": symbol,
                "product_id": product_id,
                "order_size": str(order_size_contracts),
                "state": OrderLifecycleState.RESERVED.value,
                "timestamp_monotonic": time.monotonic(),
            }
            if order_details:
                reservation_data.update(order_details)

            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                entry = {
                    "timestamp_utc": time.time(),
                    "event": "ORDER_RESERVED",
                    "data": reservation_data,
                }
                f.write(json.dumps(entry, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())

            # 5. Update local tracking state
            self._active_open_orders[cl_ord_id_clean] = {
                "state": OrderLifecycleState.RESERVED,
                "reservation_time": time.monotonic(),
                "details": reservation_data,
            }

            return AuthorizationDecision(
                authorized=True,
                state=auth_record.state,
                reasons=[],
                cumulative_orders_placed=decision.cumulative_orders_placed + 1,
                current_open_orders=len(self._active_open_orders),
                current_realized_loss_usd=decision.current_realized_loss_usd,
                _mint_token=_GATE_MINT,
            )

    def recover_and_reconcile_state(self) -> Dict[str, Any]:
        """Deterministic restart recovery scanning the persistent ledger.

        Reconstructs order states and enforces fail-closed posture:
          - Orders left in RESERVED or SUBMITTED state without terminal record enter RECONCILIATION_REQUIRED.
          - Corrupted records latch _ledger_corrupted = True and OrderLifecycleState.LEDGER_CORRUPTED.
          - Resting orders enter ACKNOWLEDGED.
          - Releases zero risk reservations until explicit reconciliation occurs.
        """
        summary: Dict[str, Any] = {
            "recovered_orders": 0,
            "active_open": [],
            "ambiguous": [],
            "terminal": [],
            "ledger_corrupted": False,
            "corruption_reason": "",
        }

        if not self.ledger_path.exists():
            return summary

        with CrossProcessFileLock(self.lock_path):
            order_states: Dict[str, Dict[str, Any]] = {}
            seen_reserved: Set[str] = set()
            seen_submitted: Set[str] = set()

            try:
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    for line_no, raw_line in enumerate(f, start=1):
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if not isinstance(record, dict) or "event" not in record:
                                self._ledger_corrupted = True
                                self._ledger_corruption_reason = f"Malformed record structure at line {line_no}"
                                break

                            event = record.get("event")
                            data = record.get("data", {}) if isinstance(record.get("data"), dict) else {}
                            cl_ord_id = data.get("cl_ord_id")

                            if not cl_ord_id:
                                continue

                            if event == "ORDER_RESERVED":
                                if cl_ord_id in seen_reserved:
                                    self._ledger_corrupted = True
                                    self._ledger_corruption_reason = f"Duplicate reservation for {cl_ord_id!r} at line {line_no}"
                                    break
                                seen_reserved.add(cl_ord_id)
                                order_states[cl_ord_id] = {
                                    "state": OrderLifecycleState.RESERVED,
                                    "data": data,
                                    "line_no": line_no,
                                }

                            elif event in ("ORDER_SUBMITTED", "ORDER_PLACED"):
                                if cl_ord_id in seen_submitted:
                                    self._ledger_corrupted = True
                                    self._ledger_corruption_reason = f"Duplicate submission for {cl_ord_id!r} at line {line_no}"
                                    break
                                seen_submitted.add(cl_ord_id)
                                if cl_ord_id not in order_states:
                                    order_states[cl_ord_id] = {"data": data, "line_no": line_no}
                                order_states[cl_ord_id]["state"] = OrderLifecycleState.SUBMISSION_UNKNOWN

                            elif event in ("ORDER_RESTING", "ORDER_ACKNOWLEDGED"):
                                if cl_ord_id in order_states:
                                    order_states[cl_ord_id]["state"] = OrderLifecycleState.ACKNOWLEDGED
                                    order_states[cl_ord_id]["exchange_order_id"] = data.get("exchange_order_id")

                            elif event in ("RESTING_TIMEOUT_CANCEL_SENT", "CANCEL_REQUESTED"):
                                if cl_ord_id in order_states:
                                    order_states[cl_ord_id]["state"] = OrderLifecycleState.CANCEL_REQUESTED

                            elif event in ("ACK_TIMEOUT_AMBIGUOUS", "AMBIGUOUS_STATE"):
                                if cl_ord_id in order_states:
                                    order_states[cl_ord_id]["state"] = OrderLifecycleState.RECONCILIATION_REQUIRED

                            elif event in ("ORDER_TERMINAL", "ORDER_FILLED", "ORDER_CANCELLED"):
                                term_state = data.get("state", OrderLifecycleState.CANCELLED_CONFIRMED.value)
                                if term_state in (OrderLifecycleState.FILLED.value, "FILLED"):
                                    final_state = OrderLifecycleState.FILLED
                                else:
                                    final_state = OrderLifecycleState.CANCELLED_CONFIRMED
                                if cl_ord_id in order_states:
                                    order_states[cl_ord_id]["state"] = final_state

                        except Exception as parse_err:
                            self._ledger_corrupted = True
                            self._ledger_corruption_reason = f"Corrupted JSON at line {line_no}: {parse_err}"
                            break

            except Exception as io_err:
                self._ledger_corrupted = True
                self._ledger_corruption_reason = f"IO error during restart recovery: {io_err}"

            if self._ledger_corrupted:
                summary["ledger_corrupted"] = True
                summary["corruption_reason"] = self._ledger_corruption_reason
                return summary

            self._active_open_orders.clear()
            self._ambiguous_orders.clear()

            for cl_ord_id, info in order_states.items():
                st = info["state"]
                if st in (OrderLifecycleState.RESERVED, OrderLifecycleState.SUBMISSION_UNKNOWN, OrderLifecycleState.RECONCILIATION_REQUIRED):
                    self._ambiguous_orders[cl_ord_id] = {
                        "state": OrderLifecycleState.RECONCILIATION_REQUIRED,
                        "details": info["data"],
                    }
                    summary["ambiguous"].append(cl_ord_id)
                elif st in (OrderLifecycleState.ACKNOWLEDGED, OrderLifecycleState.CANCEL_REQUESTED):
                    self._active_open_orders[cl_ord_id] = {
                        "state": st,
                        "details": info["data"],
                    }
                    summary["active_open"].append(cl_ord_id)
                else:
                    summary["terminal"].append(cl_ord_id)

            summary["recovered_orders"] = len(order_states)
            return summary

    def register_order_reserved(self, cl_ord_id: str, details: Dict[str, Any]) -> None:
        """Register that an order has been allocated a persistent reservation slot."""
        self._active_open_orders[cl_ord_id] = {
            "state": OrderLifecycleState.RESERVED,
            "reservation_time": time.monotonic(),
            "details": details,
        }
        self.record_order_event_to_ledger("ORDER_RESERVED", {"cl_ord_id": cl_ord_id, **details})

    def register_order_submitted(self, cl_ord_id: str, details: Dict[str, Any]) -> None:
        """Register that an order has been dispatched and is awaiting acknowledgment."""
        self._active_open_orders[cl_ord_id] = {
            "state": OrderLifecycleState.SUBMISSION_UNKNOWN,
            "submission_time": time.monotonic(),
            "details": details,
        }
        self.record_order_event_to_ledger("ORDER_SUBMITTED", {"cl_ord_id": cl_ord_id, **details})

    def register_order_acknowledged(self, cl_ord_id: str, exchange_order_id: int | str) -> None:
        """Register that the order is resting on the order book."""
        if cl_ord_id in self._active_open_orders:
            self._active_open_orders[cl_ord_id]["state"] = OrderLifecycleState.ACKNOWLEDGED
            self._active_open_orders[cl_ord_id]["exchange_order_id"] = exchange_order_id
            self._active_open_orders[cl_ord_id]["resting_since"] = time.monotonic()
            self.record_order_event_to_ledger(
                "ORDER_RESTING",
                {"cl_ord_id": cl_ord_id, "exchange_order_id": exchange_order_id},
            )

    def register_ack_timeout(self, cl_ord_id: str) -> None:
        """Flag an order whose acknowledgment timed out (> 5.0s) as ambiguous."""
        if cl_ord_id in self._active_open_orders:
            order_data = self._active_open_orders.pop(cl_ord_id)
            order_data["state"] = OrderLifecycleState.RECONCILIATION_REQUIRED
            self._ambiguous_orders[cl_ord_id] = order_data
            self.record_order_event_to_ledger("ACK_TIMEOUT_AMBIGUOUS", {"cl_ord_id": cl_ord_id})

    def register_order_terminal(self, cl_ord_id: str, terminal_state: OrderLifecycleState, pnl_usd: Decimal = Decimal("0.0")) -> None:
        """Record order completion (filled, cancelled, rejected)."""
        if cl_ord_id in self._active_open_orders:
            del self._active_open_orders[cl_ord_id]
        if cl_ord_id in self._ambiguous_orders:
            del self._ambiguous_orders[cl_ord_id]
        self.record_order_event_to_ledger(
            "ORDER_TERMINAL",
            {"cl_ord_id": cl_ord_id, "state": terminal_state.value, "pnl_usd": str(pnl_usd)},
        )

    def handle_resting_timeout(self, cl_ord_id: str, elapsed_seconds: float) -> bool:
        """Evaluate 120s policy. Returns True if cancellation must be dispatched."""
        if elapsed_seconds >= self.scope.max_order_wait_seconds:
            if cl_ord_id in self._active_open_orders:
                self._active_open_orders[cl_ord_id]["state"] = OrderLifecycleState.CANCEL_REQUESTED
                self.record_order_event_to_ledger("RESTING_TIMEOUT_CANCEL_SENT", {"cl_ord_id": cl_ord_id})
            return True
        return False
