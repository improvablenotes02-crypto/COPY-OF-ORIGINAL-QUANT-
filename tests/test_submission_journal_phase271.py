import tempfile
import unittest
from pathlib import Path

from core.execution.backup_restore_drill import run_backup_restore_drill
from core.execution.submission_journal import (
    DISPATCHING, UNKNOWN, SQLiteOrderSubmissionJournal, SubmissionJournalError,
)


class TestSubmissionJournalRestoreDrillPhase271(unittest.TestCase):
    def test_drill_restores_all_states_and_preserves_unresolved_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-drill-prepared", {"symbol": "BTC"})
            journal.reserve("QE-drill-unknown", {"symbol": "ETH"})
            journal.transition("QE-drill-unknown", DISPATCHING)
            journal.transition("QE-drill-unknown", UNKNOWN, "ambiguous venue response")
            backup = journal.backup_to(root / "backup.sqlite3")
            before = Path(backup["path"]).read_bytes()
            report = run_backup_restore_drill(
                backup["path"], expected_sha256=backup["sha256"]
            )
            self.assertEqual(report["drill_status"], "PASS")
            self.assertEqual(report["record_count"], 2)
            self.assertEqual(report["unresolved_count"], 2)
            self.assertEqual(report["state_counts"], {"PREPARED": 1, "UNKNOWN": 1})
            self.assertTrue(report["all_rows_match"])
            self.assertFalse(report["live_execution_authorized"])
            self.assertEqual(Path(backup["path"]).read_bytes(), before)

    def test_drill_requires_expected_digest_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            backup = journal.backup_to(root / "backup.sqlite3")
            with self.assertRaises(SubmissionJournalError):
                run_backup_restore_drill(backup["path"], expected_sha256="bad")
            with self.assertRaises(SubmissionJournalError):
                run_backup_restore_drill(
                    backup["path"], expected_sha256="0" * 64
                )

    def test_drill_rejects_corrupt_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrupt.sqlite3"
            path.write_bytes(b"not sqlite")
            import hashlib
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(SubmissionJournalError):
                run_backup_restore_drill(path, expected_sha256=digest)


if __name__ == "__main__":
    unittest.main()
