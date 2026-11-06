"""Read-only verification and inventory for SQLite submission-journal backups.

This module never mutates, restores, deletes, or resubmits anything. It reports
whether each supplied backup is present, byte-integrity checked, and readable
under the currently supported journal schema.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Mapping

from core.execution.submission_journal import (
    SCHEMA_VERSION,
    SQLiteOrderSubmissionJournal,
    SubmissionJournalError,
)


def verify_backup_inventory(
    paths: Iterable[str | Path],
    *,
    expected_sha256: Mapping[str, str] | None = None,
    now_ns: int | None = None,
) -> dict:
    """Return a deterministic, read-only health report for supplied backups.

    expected_sha256 keys are the exact string form of each supplied path.
    A missing expected digest does not fail verification; it is reported as
    unanchored because a locally computed hash alone is not authenticity.
    """
    reference_now = int(now_ns if now_ns is not None else time.time_ns())
    expected = dict(expected_sha256 or {})
    entries = []
    for supplied in sorted((Path(item).expanduser() for item in paths), key=lambda p: str(p)):
        label = str(supplied)
        entry = {
            "path": label,
            "status": "INVALID",
            "sha256": None,
            "expected_sha256": expected.get(label),
            "hash_status": "unanchored",
            "size_bytes": None,
            "modified_at_ns": None,
            "age_seconds": None,
            "schema_version": None,
            "record_count": None,
            "unresolved_count": None,
            "error": None,
        }
        try:
            if not supplied.is_file():
                entry.update(status="MISSING", error="backup file is missing or not a regular file")
                entries.append(entry)
                continue
            before = supplied.stat()
            digest = hashlib.sha256()
            with supplied.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            after = supplied.stat()
            if (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", None)) != (
                after.st_size, after.st_mtime_ns, getattr(after, "st_ino", None)
            ):
                raise SubmissionJournalError("backup changed while being verified")
            actual_digest = digest.hexdigest()
            expected_digest = entry["expected_sha256"]
            if expected_digest is not None:
                if (not isinstance(expected_digest, str) or len(expected_digest) != 64
                        or any(ch not in "0123456789abcdefABCDEF" for ch in expected_digest)):
                    raise SubmissionJournalError("expected SHA-256 is malformed")
                hash_status = "match" if actual_digest == expected_digest.lower() else "mismatch"
            else:
                hash_status = "unanchored"
            counts = SQLiteOrderSubmissionJournal._validate_database_file(supplied)
            entry.update(
                status="VALID" if hash_status != "mismatch" else "HASH_MISMATCH",
                sha256=actual_digest,
                hash_status=hash_status,
                size_bytes=after.st_size,
                modified_at_ns=after.st_mtime_ns,
                age_seconds=max(0.0, (reference_now - after.st_mtime_ns) / 1_000_000_000),
                schema_version=SCHEMA_VERSION,
                record_count=counts["record_count"],
                unresolved_count=counts["unresolved_count"],
            )
            if hash_status == "mismatch":
                entry["error"] = "backup SHA-256 does not match supplied expected digest"
        except (OSError, sqlite3.DatabaseError, SubmissionJournalError) as exc:
            entry["error"] = str(exc)
        entries.append(entry)
    return {
        "report_version": 1,
        "read_only": True,
        "entries": entries,
        "summary": {
            "total": len(entries),
            "valid": sum(item["status"] == "VALID" for item in entries),
            "hash_mismatch": sum(item["status"] == "HASH_MISMATCH" for item in entries),
            "missing": sum(item["status"] == "MISSING" for item in entries),
            "invalid": sum(item["status"] == "INVALID" for item in entries),
            "unresolved_records": sum(item["unresolved_count"] or 0 for item in entries),
        },
    }
