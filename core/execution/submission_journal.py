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
import os
import shutil
import sqlite3
import tempfile
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

        Caller holds a SQLite transaction to keep validation and reads consistent.
        """
        try:
            result = db.execute("PRAGMA integrity_check").fetchall()
            if result != [("ok",)]:
                raise SubmissionJournalError("submission journal SQLite integrity_check failed")
            columns = db.execute("PRAGMA table_info(order_submissions)").fetchall()
            expected = [
                ("client_order_id", "TEXT", 0, 1),
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
                db.execute("BEGIN")
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

    @classmethod
    def _validate_database_file(cls, path: str | Path) -> dict:
        """Validate a standalone journal database without initializing or mutating it."""
        probe = object.__new__(cls)
        db = sqlite3.connect(str(path), timeout=10.0, isolation_level=None)
        try:
            db.execute("BEGIN")
            try:
                probe._validate_integrity(db)
                total = db.execute("SELECT COUNT(*) FROM order_submissions").fetchone()[0]
                placeholders = ",".join("?" for _ in _UNRESOLVED)
                unresolved = db.execute(
                    f"SELECT COUNT(*) FROM order_submissions WHERE state IN ({placeholders})",
                    _UNRESOLVED,
                ).fetchone()[0]
                db.execute("COMMIT")
                return {"record_count": total, "unresolved_count": unresolved}
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        finally:
            db.close()

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _publish_file(temporary: Path, target: Path, *, overwrite: bool) -> None:
        """Atomically publish a same-filesystem temporary file.

        Without overwrite, an atomic hard-link create prevents a competing
        process from replacing an already-published destination. Unsupported
        filesystems fail closed rather than using a racy check-then-replace.
        """
        if overwrite:
            os.replace(temporary, target)
            return
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise SubmissionJournalError("destination already exists") from exc
        except OSError as exc:
            raise SubmissionJournalError(
                "atomic no-overwrite publication is unavailable on this filesystem"
            ) from exc
        temporary.unlink()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def backup_to(self, destination: str | Path, *, overwrite: bool = False) -> dict:
        """Create a consistent, validated SQLite backup and atomically publish it.

        The backup is a standalone SQLite database. The returned SHA-256 is
        an integrity fingerprint for transport/storage verification, not a
        signed authenticity guarantee.
        """
        target = Path(destination).expanduser().resolve()
        source = self.path.expanduser().resolve()
        if target == source:
            raise SubmissionJournalError("backup destination must differ from live journal")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise SubmissionJournalError("backup destination already exists")
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            with self._lock, self._connection() as source_db:
                self._validate_integrity(source_db)
                backup_db = sqlite3.connect(str(temporary), isolation_level=None)
                try:
                    source_db.backup(backup_db)
                finally:
                    backup_db.close()
            self._fsync_file(temporary)
            counts = self._validate_database_file(temporary)
            digest = self._file_sha256(temporary)
            self._publish_file(temporary, target, overwrite=overwrite)
            self._fsync_directory(target.parent)
            return {
                "path": str(target),
                "sha256": digest,
                "schema_version": SCHEMA_VERSION,
                **counts,
            }
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if isinstance(exc, SubmissionJournalError):
                raise
            raise SubmissionJournalError("submission journal backup failed") from exc

    @classmethod
    def restore_from(
        cls, backup: str | Path, destination: str | Path, *,
        expected_sha256: str | None = None, overwrite: bool = False,
    ) -> "SQLiteOrderSubmissionJournal":
        """Validate a backup fully, then atomically install it at destination."""
        source = Path(backup).expanduser().resolve()
        target = Path(destination).expanduser().resolve()
        if source == target:
            raise SubmissionJournalError("restore source and destination must differ")
        if not source.is_file():
            raise SubmissionJournalError("journal backup file does not exist")
        if target.exists() and not overwrite:
            raise SubmissionJournalError("restore destination already exists")
        try:
            cls._validate_database_file(source)
            digest = cls._file_sha256(source)
            if expected_sha256 is not None and digest.lower() != str(expected_sha256).lower():
                raise SubmissionJournalError("journal backup SHA-256 does not match expected value")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".restore", dir=target.parent)
            os.close(fd)
            temporary = Path(temp_name)
            try:
                shutil.copyfile(source, temporary)
                cls._fsync_file(temporary)
                cls._validate_database_file(temporary)
                cls._publish_file(temporary, target, overwrite=overwrite)
                cls._fsync_directory(target.parent)
            finally:
                temporary.unlink(missing_ok=True)
            return cls(target)
        except Exception as exc:
            if isinstance(exc, SubmissionJournalError):
                raise
            raise SubmissionJournalError("submission journal restore failed") from exc

    def health_report(self) -> dict:
        """Return a validated, read-only operational snapshot of journal state.

        Integrity validation and aggregate counts share one SQLite read
        transaction. The report is diagnostic only: it never authorizes live
        execution, changes records, or performs venue/network I/O.
        """
        with self._lock, self._connection() as db:
            try:
                db.execute("BEGIN")
                self._validate_integrity(db)
                total = db.execute(
                    "SELECT COUNT(*) FROM order_submissions"
                ).fetchone()[0]
                state_rows = db.execute(
                    "SELECT state, COUNT(*) FROM order_submissions GROUP BY state"
                ).fetchall()
                db.execute("COMMIT")
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        counts = {state: 0 for state in _ALLOWED}
        counts.update({state: count for state, count in state_rows})
        unresolved_count = sum(counts[state] for state in _UNRESOLVED)
        return {
            "integrity_valid": True,
            "schema_version": SCHEMA_VERSION,
            "record_count": total,
            "unresolved_count": unresolved_count,
            "state_counts": counts,
            "live_execution_authorized": False,
            "generated_at_ns": time.time_ns(),
        }

    def unresolved(self):
        """Return validated, immutable dictionaries requiring venue reconciliation.

        Integrity validation and selection share one SQLite write transaction,
        so a caller never receives a partial or unvalidated journal snapshot.
        """
        placeholders = ",".join("?" for _ in _UNRESOLVED)
        with self._lock, self._connection() as db:
            try:
                db.execute("BEGIN")
                self._validate_integrity(db)
                rows = db.execute(
                    f"""SELECT client_order_id, payload_sha256, state, detail,
                        created_at_ns, updated_at_ns, schema_version
                        FROM order_submissions WHERE state IN ({placeholders})
                        ORDER BY created_at_ns, client_order_id""",
                    _UNRESOLVED,
                ).fetchall()
                db.execute("COMMIT")
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        fields = (
            "client_order_id", "payload_sha256", "state", "detail",
            "created_at_ns", "updated_at_ns", "schema_version",
        )
        return [dict(zip(fields, row)) for row in rows]

    def get(self, client_order_id: str):
        """Return one validated journal record, or None when the ID is absent."""
        with self._lock, self._connection() as db:
            try:
                db.execute("BEGIN")
                self._validate_integrity(db)
                row = db.execute(
                    """SELECT client_order_id, payload_sha256, state, detail,
                       created_at_ns, updated_at_ns, schema_version
                       FROM order_submissions WHERE client_order_id = ?""",
                    (str(client_order_id),),
                ).fetchone()
                db.execute("COMMIT")
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        if row is None:
            return None
        return dict(zip((
            "client_order_id", "payload_sha256", "state", "detail",
            "created_at_ns", "updated_at_ns", "schema_version",
        ), row))
