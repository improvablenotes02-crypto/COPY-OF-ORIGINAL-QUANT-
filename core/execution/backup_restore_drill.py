"""Disposable, offline restore drill for submission-journal backups.

The drill restores only into a temporary directory, compares every persisted
journal row, and removes the temporary copy on exit. It never contacts a venue
or submits/retries an order.
"""
from __future__ import annotations

import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from core.execution.submission_journal import (
    SQLiteOrderSubmissionJournal,
    SubmissionJournalError,
)


def _read_rows(path: Path) -> list[tuple]:
    db = sqlite3.connect(str(path), timeout=10.0)
    try:
        db.execute("PRAGMA query_only=ON")
        return db.execute(
            """SELECT client_order_id, payload_sha256, state, detail,
               created_at_ns, updated_at_ns, schema_version
               FROM order_submissions ORDER BY client_order_id"""
        ).fetchall()
    finally:
        db.close()


def run_backup_restore_drill(
    backup_path: str | Path,
    *,
    expected_sha256: str,
) -> dict:
    """Restore a verified backup into disposable storage and compare all rows.

    A successful drill demonstrates local structural restoreability only. It
    does not prove backup authenticity beyond the supplied digest, venue
    reconciliation, broker connectivity, or permission to enable live orders.
    """
    source = Path(backup_path).expanduser().resolve()
    if not source.is_file():
        raise SubmissionJournalError("restore drill backup file does not exist")
    if (not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in expected_sha256)):
        raise SubmissionJournalError("restore drill requires a valid expected SHA-256")
    source_digest = SQLiteOrderSubmissionJournal._file_sha256(source)
    if source_digest != expected_sha256.lower():
        raise SubmissionJournalError("restore drill backup SHA-256 mismatch")
    try:
        source_counts = SQLiteOrderSubmissionJournal._validate_database_file(source)
        source_rows = _read_rows(source)
    except sqlite3.DatabaseError as exc:
        raise SubmissionJournalError("restore drill source is not a valid journal database") from exc
    with tempfile.TemporaryDirectory(prefix="quantengine-restore-drill-") as tmp:
        target = Path(tmp) / "drill-restore.sqlite3"
        restored = SQLiteOrderSubmissionJournal.restore_from(
            source, target, expected_sha256=expected_sha256
        )
        restored.validate_integrity()
        restored_counts = SQLiteOrderSubmissionJournal._validate_database_file(target)
        restored_rows = _read_rows(target)
        if source_rows != restored_rows:
            raise SubmissionJournalError("restore drill row comparison failed")
        if source_counts != restored_counts:
            raise SubmissionJournalError("restore drill record-count comparison failed")
        states = dict(sorted(Counter(row[2] for row in restored_rows).items()))
        return {
            "drill_status": "PASS",
            "read_only_source": True,
            "temporary_restore_only": True,
            "source_sha256": source_digest,
            "record_count": restored_counts["record_count"],
            "unresolved_count": restored_counts["unresolved_count"],
            "state_counts": states,
            "all_rows_match": True,
            "live_execution_authorized": False,
        }
