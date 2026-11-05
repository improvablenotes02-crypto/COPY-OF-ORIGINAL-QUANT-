"""Repository-backed, revisioned account-risk state.

SQLite is a local/single-node development adapter. Production multi-node
deployments must inject a shared transactional implementation of the protocol.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
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

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class PersistentAccountRiskCoordinator:
    """Risk coordinator using an injected transactional repository."""

    def __init__(self, repository: AccountRiskRepository):
        if not isinstance(repository, AccountRiskRepository):
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
