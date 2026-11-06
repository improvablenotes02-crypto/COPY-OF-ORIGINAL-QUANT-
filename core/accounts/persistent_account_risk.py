"""Repository-backed, revisioned account-risk state.

SQLite is a local/single-node development adapter. Production multi-node
deployments must inject a shared transactional implementation of the protocol.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
import threading
from typing import Protocol

from core.accounts.account_risk import (
    AccountRiskDecision,
    AccountRiskError,
    AccountRiskGate,
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    OrderRiskProposal,
)


class AccountRiskRepository(Protocol):
    """Transactional persistence contract for per-tenant account risk state."""

    def register(
        self, *, scope: AccountRiskScope, profile: AccountRiskProfile,
        initial_state: AccountRiskState,
    ) -> None: ...

    def get(
        self, scope: AccountRiskScope,
    ) -> tuple[AccountRiskProfile, AccountRiskState] | None: ...

    def compare_and_swap_state(
        self, *, scope: AccountRiskScope, expected_revision: int,
        state: AccountRiskState,
    ) -> AccountRiskState | None: ...

    def reserve_order(
        self, *, reservation_id: str, proposal: OrderRiskProposal,
    ) -> tuple[AccountRiskDecision, "AccountRiskReservation | None"]: ...

    def list_pending_reservations(
        self, scope: AccountRiskScope,
    ) -> tuple["AccountRiskReservation", ...]: ...

    def release_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
    ) -> bool: ...

    def settle_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
        expected_revision: int, reconciled_state: AccountRiskState,
        evidence: "AccountRiskReconciliationEvidence",
    ) -> bool: ...

    def get_reservation_evidence(
        self, *, scope: AccountRiskScope, reservation_id: str,
    ) -> "AccountRiskReconciliationEvidence | None": ...


def hash_account_risk_state(state: AccountRiskState) -> str:
    """Canonical SHA-256 identity for one validated normalized risk state."""
    if not isinstance(state, AccountRiskState):
        raise AccountRiskError("AccountRiskState is required for state hashing")
    try:
        payload = json.dumps(
            asdict(state), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AccountRiskError("risk state cannot be canonically hashed") from exc
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountRiskReservation:
    reservation_id: str
    scope: AccountRiskScope
    notional: float
    status: str
    created_revision: int

    def __post_init__(self):
        if not isinstance(self.reservation_id, str) or not self.reservation_id.strip():
            raise AccountRiskError("reservation_id is required")
        object.__setattr__(self, "reservation_id", self.reservation_id.strip())
        if not isinstance(self.status, str) or self.status not in {"PENDING", "RELEASED", "SETTLED"}:
            raise AccountRiskError("invalid account risk reservation status")
        if not isinstance(self.scope, AccountRiskScope):
            raise AccountRiskError("reservation scope is invalid")
        if (
            isinstance(self.notional, bool)
            or not isinstance(self.notional, (int, float))
            or not math.isfinite(float(self.notional))
            or self.notional <= 0
        ):
            raise AccountRiskError("reservation notional must be positive")
        if isinstance(self.created_revision, bool) or not isinstance(self.created_revision, int) or self.created_revision < 1:
            raise AccountRiskError("reservation revision must be positive")


@dataclass(frozen=True, slots=True)
class AccountRiskReconciliationEvidence:
    """Complete authenticated exchange evidence authorizing reservation settlement."""

    scope: AccountRiskScope
    reservation_id: str
    client_order_id: str
    source: str
    exchange_order_id: str
    terminal_status: str
    observed_at: str
    snapshot_hash: str
    risk_state_hash: str
    identity_verified: bool
    orders_complete: bool
    fills_complete: bool
    positions_complete: bool
    open_order_absent: bool

    def __post_init__(self):
        if not isinstance(self.scope, AccountRiskScope):
            raise AccountRiskError("reconciliation evidence scope is invalid")
        if not isinstance(self.reservation_id, str) or not self.reservation_id.strip():
            raise AccountRiskError("reconciliation evidence reservation_id is required")
        object.__setattr__(self, "reservation_id", self.reservation_id.strip())
        if not isinstance(self.client_order_id, str) or self.client_order_id.strip() != self.reservation_id:
            raise AccountRiskError("reconciliation evidence client_order_id must match reservation_id")
        object.__setattr__(self, "client_order_id", self.client_order_id.strip())
        if self.source != "DELTA_AUTHENTICATED_READ":
            raise AccountRiskError("reconciliation evidence must come from authenticated Delta reads")
        if not isinstance(self.exchange_order_id, str) or not self.exchange_order_id.strip():
            raise AccountRiskError("reconciliation evidence exchange_order_id is required")
        if not isinstance(self.terminal_status, str) or self.terminal_status not in {"FILLED", "REJECTED", "CANCELED", "CANCELLED", "EXPIRED"}:
            raise AccountRiskError("reconciliation evidence must identify a terminal exchange order status")
        if not isinstance(self.observed_at, str):
            raise AccountRiskError("reconciliation evidence observed_at must be an ISO timestamp")
        try:
            observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AccountRiskError("reconciliation evidence observed_at is invalid") from exc
        if observed.tzinfo is None or observed.utcoffset() is None or observed.utcoffset().total_seconds() != 0:
            raise AccountRiskError("reconciliation evidence observed_at must be UTC-aware")
        if not isinstance(self.snapshot_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.snapshot_hash) is None:
            raise AccountRiskError("reconciliation evidence snapshot_hash must be SHA-256 hex")
        if not isinstance(self.risk_state_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.risk_state_hash) is None:
            raise AccountRiskError("reconciliation evidence risk_state_hash must be SHA-256 hex")
        for name in ("identity_verified", "orders_complete", "fills_complete", "positions_complete", "open_order_absent"):
            if getattr(self, name) is not True:
                raise AccountRiskError(f"reconciliation evidence {name} must be true")


class SQLiteAccountRiskRepository:
    """Atomic local SQLite adapter; not a multi-node production database."""

    def __init__(self, database_path: str):
        if not isinstance(database_path, str) or not database_path.strip():
            raise ValueError("database_path is required")
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, timeout=15.0, isolation_level=None,
            check_same_thread=False,
        )
        self._connection.execute("PRAGMA foreign_keys = ON")
        if database_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account_risk_state (
                tenant_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                state_json TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 0),
                PRIMARY KEY (tenant_id, account_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account_risk_reservations (
                reservation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                proposal_json TEXT NOT NULL,
                notional REAL NOT NULL CHECK (notional > 0),
                status TEXT NOT NULL CHECK (status IN ('PENDING', 'RELEASED', 'SETTLED')),
                created_revision INTEGER NOT NULL CHECK (created_revision > 0),
                FOREIGN KEY (tenant_id, account_id)
                    REFERENCES account_risk_state (tenant_id, account_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account_risk_reservation_evidence (
                reservation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                FOREIGN KEY (reservation_id)
                    REFERENCES account_risk_reservations (reservation_id)
            )
            """
        )

    @staticmethod
    def _dump(value: dict) -> str:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise AccountRiskError("risk state is not safely JSON serializable") from exc

    @staticmethod
    def _key(scope: AccountRiskScope) -> tuple[str, str]:
        return scope.tenant_id, scope.account_id

    @staticmethod
    def _validate_state(state: AccountRiskState, scope: AccountRiskScope) -> None:
        """Reject unsafe persisted risk state before any transaction commits."""
        if not isinstance(state, AccountRiskState) or state.scope != scope:
            raise AccountRiskError("risk state must match the requested account scope")
        if (
            isinstance(state.revision, bool)
            or not isinstance(state.revision, int)
            or state.revision < 0
        ):
            raise AccountRiskError("risk state revision must be a non-negative integer")
        for name in ("risk_basis", "equity"):
            value = getattr(state, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise AccountRiskError(f"risk state {name} must be finite and positive")
        for name in ("daily_pnl", "weekly_pnl", "monthly_pnl"):
            value = getattr(state, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise AccountRiskError(f"risk state {name} must be finite")
        for name in ("current_exposure", "pending_exposure"):
            value = getattr(state, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise AccountRiskError(f"risk state {name} must be finite and non-negative")
        for name in ("open_positions", "pending_orders"):
            value = getattr(state, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AccountRiskError(f"risk state {name} must be a non-negative integer")
        if not isinstance(state.kill_switch, bool) or not isinstance(state.trading_enabled, bool):
            raise AccountRiskError("risk state trading controls must be boolean")

    def register(
        self, *, scope: AccountRiskScope, profile: AccountRiskProfile,
        initial_state: AccountRiskState,
    ) -> None:
        if not isinstance(scope, AccountRiskScope):
            raise AccountRiskError("valid account risk scope is required")
        if not isinstance(profile, AccountRiskProfile):
            raise AccountRiskError("explicit account risk profile is required")
        self._validate_state(initial_state, scope)
        if initial_state.revision != 0:
            raise AccountRiskError("initial risk state revision must be zero")
        scope_json = self._dump(asdict(scope))
        profile_json = self._dump(asdict(profile))
        state_data = asdict(initial_state)
        state_data.pop("scope", None)
        state_json = self._dump(state_data)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT INTO account_risk_state
                    (tenant_id, account_id, scope_json, profile_json, state_json, revision)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (*self._key(scope), scope_json, profile_json, state_json),
                )
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._connection.execute("ROLLBACK")
                raise AccountRiskError(
                    "risk profile already registered for this tenant account"
                ) from exc
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def get(
        self, scope: AccountRiskScope,
    ) -> tuple[AccountRiskProfile, AccountRiskState] | None:
        if not isinstance(scope, AccountRiskScope):
            raise AccountRiskError("valid account risk scope is required")
        with self._lock:
            row = self._connection.execute(
                """
                SELECT scope_json, profile_json, state_json, revision
                FROM account_risk_state WHERE tenant_id = ? AND account_id = ?
                """,
                self._key(scope),
            ).fetchone()
        if row is None:
            return None
        scope_data, profile_data, state_data, revision = row
        stored_scope = AccountRiskScope(**json.loads(scope_data))
        if stored_scope != scope:
            raise AccountRiskError("persisted risk scope does not match requested account")
        profile = AccountRiskProfile(**json.loads(profile_data))
        state_values = json.loads(state_data)
        if state_values.get("revision") != revision:
            raise AccountRiskError("persisted risk state revision is inconsistent")
        state = AccountRiskState(scope=stored_scope, **state_values)
        self._validate_state(state, stored_scope)
        return profile, state

    def compare_and_swap_state(
        self, *, scope: AccountRiskScope, expected_revision: int,
        state: AccountRiskState,
    ) -> AccountRiskState | None:
        if not isinstance(scope, AccountRiskScope) or not isinstance(state, AccountRiskState):
            raise AccountRiskError("valid account scope and risk state are required")
        self._validate_state(state, scope)
        if state.revision != expected_revision:
            raise AccountRiskError("risk state revision does not match expected_revision")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise AccountRiskError("expected_revision must be a non-negative integer")
        next_state = replace(state, revision=expected_revision + 1)
        state_data = asdict(next_state)
        state_data.pop("scope", None)
        state_json = self._dump(state_data)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._connection.execute(
                    """
                    UPDATE account_risk_state
                    SET state_json = ?, revision = ?
                    WHERE tenant_id = ? AND account_id = ? AND revision = ?
                    """,
                    (state_json, expected_revision + 1, *self._key(scope), expected_revision),
                )
                if cursor.rowcount != 1:
                    self._connection.execute("ROLLBACK")
                    return None
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return next_state

    def reserve_order(
        self, *, reservation_id: str, proposal: OrderRiskProposal,
    ) -> tuple[AccountRiskDecision, AccountRiskReservation | None]:
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise AccountRiskError("reservation_id is required")
        reservation_id = reservation_id.strip()
        if not isinstance(proposal, OrderRiskProposal) or not isinstance(proposal.scope, AccountRiskScope):
            raise AccountRiskError("valid order risk proposal is required")
        scope = proposal.scope
        proposal_json = self._dump({
            "scope": asdict(scope),
            "risk_amount": float(proposal.risk_amount),
            "notional": float(proposal.notional),
            "leverage": float(proposal.leverage),
        })
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._connection.execute(
                    """
                    SELECT tenant_id, account_id, proposal_json, notional,
                           status, created_revision
                    FROM account_risk_reservations WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                ).fetchone()
                if existing is not None:
                    tenant_id, account_id, existing_json, notional, status, created_revision = existing
                    if (tenant_id, account_id) != self._key(scope) or existing_json != proposal_json:
                        raise AccountRiskError("reservation_id is already bound to a different proposal")
                    stored = self.get(scope)
                    if stored is None:
                        raise AccountRiskError("reservation account risk profile is missing")
                    profile, state = stored
                    reservation = AccountRiskReservation(
                        reservation_id, scope, float(notional), status, int(created_revision)
                    )
                    if status == "PENDING":
                        decision = AccountRiskDecision(
                            True, "ACCOUNT_RISK_RESERVATION_ALREADY_EXISTS", scope,
                            float(state.equity) * float(profile.risk_per_trade_fraction),
                            min(float(profile.max_order_notional), float(state.equity) * float(profile.max_leverage)),
                        )
                        self._connection.execute("COMMIT")
                        return decision, reservation
                    decision = AccountRiskDecision(
                        False, f"ACCOUNT_RISK_RESERVATION_{status}", scope, 0.0, 0.0
                    )
                    self._connection.execute("COMMIT")
                    return decision, None

                stored = self.get(scope)
                if stored is None:
                    decision = AccountRiskDecision(
                        False, "ACCOUNT_RISK_PROFILE_MISSING", scope, 0.0, 0.0
                    )
                    self._connection.execute("ROLLBACK")
                    return decision, None
                profile, state = stored
                decision = AccountRiskGate.evaluate(profile, state, proposal)
                if not decision.allowed:
                    self._connection.execute("ROLLBACK")
                    return decision, None
                next_state = replace(
                    state,
                    pending_orders=state.pending_orders + 1,
                    pending_exposure=state.pending_exposure + float(proposal.notional),
                    revision=state.revision + 1,
                )
                state_data = asdict(next_state)
                state_data.pop("scope", None)
                cursor = self._connection.execute(
                    """
                    UPDATE account_risk_state
                    SET state_json = ?, revision = ?
                    WHERE tenant_id = ? AND account_id = ? AND revision = ?
                    """,
                    (
                        self._dump(state_data), next_state.revision,
                        *self._key(scope), state.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AccountRiskError("risk state changed during atomic reservation")
                self._connection.execute(
                    """
                    INSERT INTO account_risk_reservations
                    (reservation_id, tenant_id, account_id, proposal_json, notional, status, created_revision)
                    VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (
                        reservation_id, *self._key(scope), proposal_json,
                        float(proposal.notional), next_state.revision,
                    ),
                )
                self._connection.execute("COMMIT")
                reservation = AccountRiskReservation(
                    reservation_id, scope, float(proposal.notional),
                    "PENDING", next_state.revision,
                )
                return AccountRiskDecision(
                    True, "ACCOUNT_RISK_RESERVED", scope,
                    decision.maximum_risk_amount, decision.maximum_notional,
                ), reservation
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def list_pending_reservations(
        self, scope: AccountRiskScope,
    ) -> tuple[AccountRiskReservation, ...]:
        if not isinstance(scope, AccountRiskScope):
            raise AccountRiskError("valid account risk scope is required")
        stored = self.get(scope)
        if stored is None:
            return ()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT reservation_id, notional, status, created_revision
                FROM account_risk_reservations
                WHERE tenant_id = ? AND account_id = ? AND status = 'PENDING'
                ORDER BY created_revision, reservation_id
                """,
                self._key(scope),
            ).fetchall()
        return tuple(
            AccountRiskReservation(
                reservation_id=row[0], scope=scope, notional=float(row[1]),
                status=row[2], created_revision=int(row[3]),
            )
            for row in rows
        )

    def release_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
    ) -> bool:
        if not isinstance(scope, AccountRiskScope):
            raise AccountRiskError("valid account risk scope is required")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT tenant_id, account_id, notional, status
                    FROM account_risk_reservations WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    self._connection.execute("ROLLBACK")
                    return False
                tenant_id, account_id, notional, status = row
                if (tenant_id, account_id) != self._key(scope):
                    raise AccountRiskError("reservation scope mismatch")
                if status != "PENDING":
                    self._connection.execute("COMMIT")
                    return False
                stored = self.get(scope)
                if stored is None:
                    raise AccountRiskError("reservation account risk state is missing")
                _, state = stored
                if state.pending_orders < 1 or state.pending_exposure < float(notional):
                    raise AccountRiskError("pending risk state cannot cover reservation release")
                next_state = replace(
                    state,
                    pending_orders=state.pending_orders - 1,
                    pending_exposure=state.pending_exposure - float(notional),
                    revision=state.revision + 1,
                )
                state_data = asdict(next_state)
                state_data.pop("scope", None)
                cursor = self._connection.execute(
                    """
                    UPDATE account_risk_state SET state_json = ?, revision = ?
                    WHERE tenant_id = ? AND account_id = ? AND revision = ?
                    """,
                    (self._dump(state_data), next_state.revision, *self._key(scope), state.revision),
                )
                if cursor.rowcount != 1:
                    raise AccountRiskError("risk state changed during reservation release")
                self._connection.execute(
                    "UPDATE account_risk_reservations SET status = 'RELEASED' WHERE reservation_id = ?",
                    (reservation_id,),
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def settle_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
        expected_revision: int, reconciled_state: AccountRiskState,
        evidence: AccountRiskReconciliationEvidence,
    ) -> bool:
        if not isinstance(scope, AccountRiskScope) or not isinstance(reconciled_state, AccountRiskState):
            raise AccountRiskError("valid account scope and reconciled risk state are required")
        self._validate_state(reconciled_state, scope)
        if not isinstance(evidence, AccountRiskReconciliationEvidence):
            raise AccountRiskError("complete authenticated reconciliation evidence is required")
        if evidence.scope != scope or evidence.reservation_id != reservation_id:
            raise AccountRiskError("reconciliation evidence does not match reservation scope and ID")
        if evidence.risk_state_hash != hash_account_risk_state(reconciled_state):
            raise AccountRiskError("reconciliation evidence does not bind the committed risk state")
        if evidence.terminal_status != "REJECTED":
            raise AccountRiskError(
                "settlement requires a rejected order; executed or cancelled orders need "
                "independent position reconciliation"
            )
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
            or reconciled_state.revision != expected_revision
        ):
            raise AccountRiskError("reconciled state scope/revision mismatch")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT tenant_id, account_id, status, notional
                    FROM account_risk_reservations WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    self._connection.execute("ROLLBACK")
                    return False
                tenant_id, account_id, status, reservation_notional = row
                if (tenant_id, account_id) != self._key(scope):
                    raise AccountRiskError("reservation scope mismatch")
                if status != "PENDING":
                    self._connection.execute("COMMIT")
                    return False
                stored = self.get(scope)
                if stored is None:
                    raise AccountRiskError("reservation account risk state is missing")
                _, current_state = stored
                if current_state.revision != expected_revision:
                    raise AccountRiskError("stale risk revision during reservation settlement")
                if (
                    current_state.pending_orders < 1
                    or current_state.pending_exposure + 1e-9 < float(reservation_notional)
                ):
                    raise AccountRiskError("current risk state cannot cover the pending reservation")
                expected_pending_orders = current_state.pending_orders - 1
                expected_pending_exposure = max(
                    0.0, current_state.pending_exposure - float(reservation_notional)
                )
                if (
                    reconciled_state.pending_orders != expected_pending_orders
                    or not math.isclose(
                        reconciled_state.pending_exposure,
                        expected_pending_exposure,
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    )
                ):
                    raise AccountRiskError(
                        "settlement must release exactly the target pending reservation"
                    )
                unchanged_projection = replace(
                    reconciled_state,
                    pending_orders=current_state.pending_orders,
                    pending_exposure=current_state.pending_exposure,
                )
                if unchanged_projection != current_state:
                    raise AccountRiskError(
                        "rejected-order settlement may only release its own pending reservation; "
                        "all other risk fields must remain unchanged"
                    )
                next_state = replace(reconciled_state, revision=expected_revision + 1)
                state_data = asdict(next_state)
                state_data.pop("scope", None)
                cursor = self._connection.execute(
                    """
                    UPDATE account_risk_state SET state_json = ?, revision = ?
                    WHERE tenant_id = ? AND account_id = ? AND revision = ?
                    """,
                    (self._dump(state_data), next_state.revision, *self._key(scope), expected_revision),
                )
                if cursor.rowcount != 1:
                    raise AccountRiskError("risk state changed during reservation settlement")
                self._connection.execute(
                    "UPDATE account_risk_reservations SET status = 'SETTLED' WHERE reservation_id = ?",
                    (reservation_id,),
                )
                evidence_json = self._dump({
                    "scope": asdict(evidence.scope),
                    "reservation_id": evidence.reservation_id,
                    "client_order_id": evidence.client_order_id,
                    "source": evidence.source,
                    "exchange_order_id": evidence.exchange_order_id,
                    "terminal_status": evidence.terminal_status,
                    "observed_at": evidence.observed_at,
                    "snapshot_hash": evidence.snapshot_hash,
                    "risk_state_hash": evidence.risk_state_hash,
                    "identity_verified": evidence.identity_verified,
                    "orders_complete": evidence.orders_complete,
                    "fills_complete": evidence.fills_complete,
                    "positions_complete": evidence.positions_complete,
                    "open_order_absent": evidence.open_order_absent,
                })
                self._connection.execute(
                    """
                    INSERT INTO account_risk_reservation_evidence
                    (reservation_id, tenant_id, account_id, evidence_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (reservation_id, *self._key(scope), evidence_json),
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def get_reservation_evidence(
        self, *, scope: AccountRiskScope, reservation_id: str,
    ) -> AccountRiskReconciliationEvidence | None:
        if not isinstance(scope, AccountRiskScope):
            raise AccountRiskError("valid account risk scope is required")
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise AccountRiskError("reservation_id is required")
        with self._lock:
            row = self._connection.execute(
                """
                SELECT tenant_id, account_id, evidence_json
                FROM account_risk_reservation_evidence WHERE reservation_id = ?
                """,
                (reservation_id.strip(),),
            ).fetchone()
        if row is None:
            return None
        tenant_id, account_id, payload = row
        if (tenant_id, account_id) != self._key(scope):
            raise AccountRiskError("reconciliation evidence scope mismatch")
        data = json.loads(payload)
        evidence_scope = AccountRiskScope(**data.pop("scope"))
        evidence = AccountRiskReconciliationEvidence(scope=evidence_scope, **data)
        if evidence.scope != scope or evidence.reservation_id != reservation_id.strip():
            raise AccountRiskError("persisted reconciliation evidence identity mismatch")
        return evidence

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class PersistentAccountRiskCoordinator:
    """Risk coordinator using an injected transactional repository."""

    def __init__(self, repository: AccountRiskRepository):
        required = ("register", "get", "compare_and_swap_state")
        if any(not callable(getattr(repository, name, None)) for name in required):
            raise AccountRiskError("an AccountRiskRepository implementation is required")
        self._repository = repository

    def register(
        self, *, scope: AccountRiskScope, profile: AccountRiskProfile,
        initial_state: AccountRiskState,
    ) -> None:
        self._repository.register(
            scope=scope, profile=profile, initial_state=initial_state
        )

    def get_state(
        self, scope: AccountRiskScope,
    ) -> tuple[AccountRiskProfile, AccountRiskState] | None:
        return self._repository.get(scope)

    def update_state(
        self, *, scope: AccountRiskScope, expected_revision: int,
        state: AccountRiskState,
    ) -> AccountRiskState:
        updated = self._repository.compare_and_swap_state(
            scope=scope, expected_revision=expected_revision, state=state
        )
        if updated is None:
            raise AccountRiskError("stale risk state revision; refresh before retrying")
        return updated

    def reserve_order(
        self, *, reservation_id: str, proposal: OrderRiskProposal,
    ) -> tuple[AccountRiskDecision, AccountRiskReservation | None]:
        reserve = getattr(self._repository, "reserve_order", None)
        if not callable(reserve):
            raise AccountRiskError("repository does not support atomic order reservations")
        return reserve(reservation_id=reservation_id, proposal=proposal)

    def list_pending_reservations(
        self, scope: AccountRiskScope,
    ) -> tuple[AccountRiskReservation, ...]:
        list_pending = getattr(self._repository, "list_pending_reservations", None)
        if not callable(list_pending):
            raise AccountRiskError("repository does not support pending reservation recovery")
        return list_pending(scope)

    def release_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
    ) -> bool:
        release = getattr(self._repository, "release_reservation", None)
        if not callable(release):
            raise AccountRiskError("repository does not support reservation release")
        return release(scope=scope, reservation_id=reservation_id)

    def settle_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
        expected_revision: int, reconciled_state: AccountRiskState,
        evidence: AccountRiskReconciliationEvidence,
    ) -> bool:
        settle = getattr(self._repository, "settle_reservation", None)
        if not callable(settle):
            raise AccountRiskError("repository does not support reservation settlement")
        return settle(
            scope=scope, reservation_id=reservation_id,
            expected_revision=expected_revision, reconciled_state=reconciled_state,
            evidence=evidence,
        )

    def get_reservation_evidence(
        self, *, scope: AccountRiskScope, reservation_id: str,
    ) -> AccountRiskReconciliationEvidence | None:
        getter = getattr(self._repository, "get_reservation_evidence", None)
        if not callable(getter):
            raise AccountRiskError("repository does not support reconciliation evidence retrieval")
        return getter(scope=scope, reservation_id=reservation_id)

    def evaluate(self, proposal: OrderRiskProposal) -> AccountRiskDecision:
        if not isinstance(proposal, OrderRiskProposal):
            raise AccountRiskError("OrderRiskProposal is required")
        record = self._repository.get(proposal.scope)
        if record is None:
            return AccountRiskDecision(
                False, "ACCOUNT_RISK_PROFILE_MISSING", proposal.scope, 0.0, 0.0
            )
        profile, state = record
        return AccountRiskGate.evaluate(profile, state, proposal)
