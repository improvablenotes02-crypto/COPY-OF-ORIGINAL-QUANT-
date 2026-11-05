import tempfile
import unittest
from pathlib import Path

from core.execution.backup_inventory import verify_backup_inventory
from core.execution.submission_journal import (
    DISPATCHING, UNKNOWN, SQLiteOrderSubmissionJournal,
)


class TestSubmissionJournalBackupInventoryPhase270(unittest.TestCase):
    def test_valid_backup_reports_integrity_counts_and_expected_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-inventory-unknown", {"symbol": "BTC"})
            journal.transition("QE-inventory-unknown", DISPATCHING)
            journal.transition("QE-inventory-unknown", UNKNOWN, "venue ack unknown")
            backup = journal.backup_to(root / "backup.sqlite3")
            path = Path(backup["path"])
            report = verify_backup_inventory(
                [backup["path"]],
                expected_sha256={backup["path"]: backup["sha256"]},
                now_ns=path.stat().st_mtime_ns + 5_000_000_000,
            )
            item = report["entries"][0]
            self.assertEqual(item["status"], "VALID")
            self.assertEqual(item["hash_status"], "match")
            self.assertEqual(item["record_count"], 1)
            self.assertEqual(item["unresolved_count"], 1)
            self.assertEqual(item["age_seconds"], 5.0)
            self.assertTrue(report["read_only"])
            self.assertEqual(report["summary"]["unresolved_records"], 1)

    def test_hash_mismatch_is_reported_without_mutating_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-inventory-hash", {})
            backup = journal.backup_to(root / "backup.sqlite3")
            before = Path(backup["path"]).read_bytes()
            report = verify_backup_inventory(
                [backup["path"]],
                expected_sha256={backup["path"]: "0" * 64},
            )
            self.assertEqual(report["entries"][0]["status"], "HASH_MISMATCH")
            self.assertEqual(Path(backup["path"]).read_bytes(), before)

    def test_missing_corrupt_and_unanchored_backups_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corrupt = root / "corrupt.sqlite3"
            corrupt.write_bytes(b"not sqlite")
            missing = root / "missing.sqlite3"
            report = verify_backup_inventory([missing, corrupt])
            self.assertEqual(report["summary"]["missing"], 1)
            self.assertEqual(report["summary"]["invalid"], 1)
            self.assertEqual(report["entries"][0]["status"], "INVALID")
            self.assertEqual(report["entries"][0]["hash_status"], "unanchored")
            self.assertEqual(report["entries"][1]["status"], "MISSING")

    def test_inventory_does_not_modify_live_journal_or_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-inventory-readonly", {"qty": 1})
            backup = journal.backup_to(root / "backup.sqlite3")
            backup_path = Path(backup["path"])
            before = (backup_path.read_bytes(), backup_path.stat().st_mtime_ns)
            live_before = journal.get("QE-inventory-readonly")
            verify_backup_inventory([backup_path])
            after = (backup_path.read_bytes(), backup_path.stat().st_mtime_ns)
            self.assertEqual(after, before)
            self.assertEqual(journal.get("QE-inventory-readonly"), live_before)


if __name__ == "__main__":
    unittest.main()
