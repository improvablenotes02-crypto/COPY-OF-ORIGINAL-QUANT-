"""Repository-backed, revisioned account-risk state.

SQLite is a local/single-node development adapter. Production multi-node
deployments must inject a shared transactional implementation of the protocol.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import math
import sqlite3
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

    def release_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
    ) -> bool: ...

    def settle_reservation(
        self, *, scope: AccountRiskScope, reservation_id: str,
        expected_revision: int, reconciled_state: AccountRiskState,
    ) -> bool: ...


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

    def register(
        self, *, scope: AccountRiskScope, profile: AccountRiskProfile,
        initial_state: AccountRiskState,
    ) -> None:
        if not isinstance(scope, AccountRiskScope):
            raise AccountRiskError("valid account risk scope is required")
        if not isinstance(profile, AccountRiskProfile):
            raise AccountRiskError("explicit account risk profile is required")
        if not isinstance(initial_state, AccountRiskState) or initial_state.scope != scope:
            raise AccountRiskError("initial risk state must match account scope")
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
        return profile, state

    def compare_and_swap_state(
        self, *, scope: AccountRiskScope, expected_revision: int,
        state: AccountRiskState,
    ) -> AccountRiskState | None:
        if not isinstance(scope, AccountRiskScope) or not isinstance(state, AccountRiskState):
            raise AccountRiskError("valid account scope and risk state are required")
        if state.scope != scope:
            raise AccountRiskError("risk state scope does not match account")
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
    ) -> bool:
        if not isinstance(scope, AccountRiskScope) or not isinstance(reconciled_state, AccountRiskState):
            raise AccountRiskError("valid account scope and reconciled risk state are required")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
            or reconciled_state.scope != scope
            or reconciled_state.revision != expected_revision
        ):
            raise AccountRiskError("reconciled state scope/revision mismatch")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT tenant_id, account_id, status
                    FROM account_risk_reservations WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                ).fetchone()
                if row is None:
                    self._connection.execute("ROLLBACK")
                    return False
                tenant_id, account_id, status = row
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
                self._connection.execute("COMMIT")
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

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
    ) -> bool:
        settle = getattr(self._repository, "settle_reservation", None)
        if not callable(settle):
            raise AccountRiskError("repository does not support reservation settlement")
        return settle(
            scope=scope, reservation_id=reservation_id,
            expected_revision=expected_revision, reconciled_state=reconciled_state,
        )

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
