"""Durable, fail-closed order submission journal.

SQLite is used as a local write-ahead reservation store. A client order ID is
unique for the lifetime of the journal. The journal stores a payload digest,
not credentials or the full order payload. PREPARED and DISPATCHING records
survive restarts and are deliberately treated as unresolved until an
authoritative venue reconciliation is recorded.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
PREPARED = "PREPARED"
DISPATCHING = "DISPATCHING"
ACKNOWLEDGED = "ACKNOWLEDGED"
FILLED = "FILLED"
PARTIAL = "PARTIAL"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"
UNKNOWN = "UNKNOWN"
RECONCILED = "RECONCILED"

_ALLOWED = {
    PREPARED: {DISPATCHING, UNKNOWN, RECONCILED},
    DISPATCHING: {ACKNOWLEDGED, FILLED, PARTIAL, REJECTED, CANCELLED, EXPIRED, UNKNOWN},
    ACKNOWLEDGED: {FILLED, PARTIAL, CANCELLED, EXPIRED, UNKNOWN, RECONCILED},
    FILLED: {RECONCILED},
    PARTIAL: {RECONCILED},
    REJECTED: {RECONCILED},
    CANCELLED: {RECONCILED},
    EXPIRED: {RECONCILED},
    UNKNOWN: {ACKNOWLEDGED, FILLED, PARTIAL, REJECTED, CANCELLED, EXPIRED, RECONCILED},
    RECONCILED: set(),
}
_UNRESOLVED = (PREPARED, DISPATCHING, UNKNOWN)


class SubmissionJournalError(RuntimeError):
    """Journal durability or lifecycle invariant failed."""


class SQLiteOrderSubmissionJournal:
    """Cross-process unique reservation with SQLite FULL synchronous commits.

    Use a persistent local filesystem path, not a temporary directory or a
    network filesystem with unknown SQLite locking semantics. The caller must
    reconcile unresolved rows against authoritative venue order history.
    """

    def __init__(self, path: str | Path, *, timeout_seconds: float = 10.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._lock = threading.RLock()
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS order_submissions (
                    client_order_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_order_submissions_state "
                "ON order_submissions(state)"
            )

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(
            str(self.path), timeout=self.timeout_seconds, isolation_level=None
        )
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _digest(payload) -> str:
        try:
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SubmissionJournalError("payload is not canonical JSON") from exc
        return hashlib.sha256(encoded).hexdigest()

    def _validate_integrity(self, db) -> None:
        """Validate SQLite pages, schema, and all persisted journal records.

        Caller holds a write transaction to prevent concurrent mutation.
        """
        try:
            result = db.execute("PRAGMA integrity_check").fetchall()
            if result != [("ok",)]:
                raise SubmissionJournalError("submission journal SQLite integrity_check failed")
            columns = db.execute("PRAGMA table_info(order_submissions)").fetchall()
            expected = [
                ("client_order_id", "TEXT", 1, 1),
                ("payload_sha256", "TEXT", 1, 0),
                ("state", "TEXT", 1, 0),
                ("detail", "TEXT", 1, 0),
                ("created_at_ns", "INTEGER", 1, 0),
                ("updated_at_ns", "INTEGER", 1, 0),
                ("schema_version", "INTEGER", 1, 0),
            ]
            actual = [(row[1], str(row[2]).upper(), row[3], row[5]) for row in columns]
            if actual != expected:
                raise SubmissionJournalError("submission journal schema does not match supported version")
            rows = db.execute(
                """SELECT client_order_id, payload_sha256, state, detail,
                   created_at_ns, updated_at_ns, schema_version
                   FROM order_submissions"""
            ).fetchall()
            for key, digest, state, detail, created, updated, version in rows:
                if not isinstance(key, str) or not key.strip():
                    raise SubmissionJournalError("journal contains an invalid client order ID")
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(ch not in "0123456789abcdef" for ch in digest)):
                    raise SubmissionJournalError("journal contains an invalid payload digest")
                if state not in _ALLOWED:
                    raise SubmissionJournalError("journal contains an unsupported state")
                if not isinstance(detail, str):
                    raise SubmissionJournalError("journal contains invalid detail data")
                if (type(created) is not int or type(updated) is not int
                        or created <= 0 or updated < created):
                    raise SubmissionJournalError("journal contains invalid timestamps")
                if version != SCHEMA_VERSION:
                    raise SubmissionJournalError("journal contains an unsupported schema version")
        except sqlite3.DatabaseError as exc:
            raise SubmissionJournalError("submission journal integrity validation failed") from exc

    def validate_integrity(self) -> bool:
        """Run a fail-closed integrity/schema/record certification pass."""
        with self._lock, self._connection() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                self._validate_integrity(db)
                db.execute("COMMIT")
                return True
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def reserve(self, client_order_id: str, payload) -> bool:
        """Durably reserve an ID. False means it already exists, in any state."""
        key = str(client_order_id or "").strip()
        if not key:
            raise ValueError("client_order_id is required")
        digest = self._digest(payload)
        now = time.time_ns()
        with self._lock, self._connection() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                self._validate_integrity(db)
                db.execute(
                    """INSERT INTO order_submissions
                    (client_order_id, payload_sha256, state, detail,
                     created_at_ns, updated_at_ns, schema_version)
                    VALUES (?, ?, ?, '', ?, ?, ?)""",
                    (key, digest, PREPARED, now, now, SCHEMA_VERSION),
                )
                db.execute("COMMIT")
                return True
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                return False
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def transition(self, client_order_id: str, state: str, detail: str = "") -> None:
        target = str(state).upper()
        if target not in _ALLOWED:
            raise ValueError(f"unsupported submission state: {target}")
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_integrity(db)
            row = db.execute(
                "SELECT state FROM order_submissions WHERE client_order_id = ?",
                (str(client_order_id),),
            ).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise SubmissionJournalError("submission reservation not found")
            current = row[0]
            if target not in _ALLOWED[current]:
                db.execute("ROLLBACK")
                raise SubmissionJournalError(
                    f"invalid submission transition {current} -> {target}"
                )
            db.execute(
                """UPDATE order_submissions SET state = ?, detail = ?,
                   updated_at_ns = ? WHERE client_order_id = ?""",
                (target, str(detail)[:500], time.time_ns(), str(client_order_id)),
            )
            db.execute("COMMIT")

    def unresolved(self):
        """Return immutable dictionaries for rows requiring venue reconciliation."""
        placeholders = ",".join("?" for _ in _UNRESOLVED)
        with self._connection() as db:
            rows = db.execute(
                f"""SELECT client_order_id, payload_sha256, state, detail,
                    created_at_ns, updated_at_ns, schema_version
                    FROM order_submissions WHERE state IN ({placeholders})
                    ORDER BY created_at_ns, client_order_id""",
                _UNRESOLVED,
            ).fetchall()
        fields = (
            "client_order_id", "payload_sha256", "state", "detail",
            "created_at_ns", "updated_at_ns", "schema_version",
        )
        return [dict(zip(fields, row)) for row in rows]

    def get(self, client_order_id: str):
        with self._connection() as db:
            row = db.execute(
                """SELECT client_order_id, payload_sha256, state, detail,
                   created_at_ns, updated_at_ns, schema_version
                   FROM order_submissions WHERE client_order_id = ?""",
                (str(client_order_id),),
            ).fetchone()
        if row is None:
            return None
        return dict(zip((
            "client_order_id", "payload_sha256", "state", "detail",
            "created_at_ns", "updated_at_ns", "schema_version",
        ), row))
