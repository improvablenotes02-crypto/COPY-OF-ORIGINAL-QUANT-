import tempfile
import unittest
from pathlib import Path

from core.execution.submission_journal import (
    DISPATCHING, UNKNOWN, SQLiteOrderSubmissionJournal, SubmissionJournalError,
)


class TestSubmissionJournalBackupRestorePhase268(unittest.TestCase):
    def test_backup_and_restore_preserve_unresolved_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            live.reserve("QE-unresolved", {"symbol": "BTC", "qty": 2})
            live.transition("QE-unresolved", DISPATCHING)
            live.transition("QE-unresolved", UNKNOWN, "lost acknowledgement")

            backup = live.backup_to(root / "backup.sqlite3")
            self.assertEqual(backup["record_count"], 1)
            self.assertEqual(backup["unresolved_count"], 1)
            self.assertEqual(len(backup["sha256"]), 64)

            restored = SQLiteOrderSubmissionJournal.restore_from(
                backup["path"], root / "restored.sqlite3",
                expected_sha256=backup["sha256"],
            )
            self.assertTrue(restored.validate_integrity())
            self.assertEqual(restored.get("QE-unresolved")["state"], UNKNOWN)
            self.assertEqual(len(restored.unresolved()), 1)
            self.assertFalse(restored.reserve(
                "QE-unresolved", {"symbol": "BTC", "qty": 2}
            ))

    def test_restore_rejects_hash_mismatch_without_creating_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-1", {})
            backup = journal.backup_to(root / "backup.sqlite3")
            target = root / "restored.sqlite3"
            with self.assertRaises(SubmissionJournalError):
                SQLiteOrderSubmissionJournal.restore_from(
                    backup["path"], target, expected_sha256="0" * 64
                )
            self.assertFalse(target.exists())

    def test_restore_rejects_corrupt_backup_without_creating_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "corrupt.sqlite3"
            bad.write_bytes(b"not a sqlite database")
            target = root / "restored.sqlite3"
            with self.assertRaises(SubmissionJournalError):
                SQLiteOrderSubmissionJournal.restore_from(bad, target)
            self.assertFalse(target.exists())

    def test_backup_and_restore_do_not_overwrite_without_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-1", {})
            backup_path = root / "backup.sqlite3"
            journal.backup_to(backup_path)
            with self.assertRaises(SubmissionJournalError):
                journal.backup_to(backup_path)
            destination = root / "restored.sqlite3"
            destination.write_bytes(b"keep-existing")
            with self.assertRaises(SubmissionJournalError):
                SQLiteOrderSubmissionJournal.restore_from(backup_path, destination)
            self.assertEqual(destination.read_bytes(), b"keep-existing")


if __name__ == "__main__":
    unittest.main()
