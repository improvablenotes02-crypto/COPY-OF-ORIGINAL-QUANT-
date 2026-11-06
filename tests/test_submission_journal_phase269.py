import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.execution.submission_journal import (
    SQLiteOrderSubmissionJournal, SubmissionJournalError,
)


class TestSubmissionJournalAtomicPublishPhase269(unittest.TestCase):
    def test_concurrent_no_overwrite_backup_has_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-atomic", {"symbol": "BTC"})
            target = root / "shared-backup.sqlite3"

            def publish():
                try:
                    return journal.backup_to(target)
                except SubmissionJournalError:
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: publish(), range(2)))

            self.assertEqual(sum(item is not None for item in results), 1)
            self.assertTrue(target.is_file())
            self.assertEqual(
                SQLiteOrderSubmissionJournal._validate_database_file(target)["record_count"], 1
            )

    def test_concurrent_no_overwrite_restore_has_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-restore-atomic", {"symbol": "ETH"})
            backup = journal.backup_to(root / "backup.sqlite3")["path"]
            target = root / "restored.sqlite3"

            def restore():
                try:
                    SQLiteOrderSubmissionJournal.restore_from(backup, target)
                    return True
                except SubmissionJournalError:
                    return False

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: restore(), range(2)))

            self.assertEqual(sum(results), 1)
            restored = SQLiteOrderSubmissionJournal(target)
            self.assertEqual(restored.get("QE-restore-atomic")["state"], "PREPARED")
            self.assertTrue(restored.validate_integrity())

    def test_explicit_overwrite_still_replaces_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            journal.reserve("QE-replace", {"symbol": "SOL"})
            target = root / "backup.sqlite3"
            target.write_bytes(b"old")
            result = journal.backup_to(target, overwrite=True)
            self.assertEqual(len(result["sha256"]), 64)
            self.assertEqual(
                SQLiteOrderSubmissionJournal._validate_database_file(target)["record_count"], 1
            )


if __name__ == "__main__":
    unittest.main()
