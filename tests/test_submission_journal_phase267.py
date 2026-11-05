import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.execution.submission_journal import (
    DISPATCHING, SQLiteOrderSubmissionJournal, SubmissionJournalError,
)


class TestSubmissionJournalIntegrityPhase267(unittest.TestCase):
    def test_integrity_passes_after_restart_and_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            journal.reserve("QE-1", {"symbol": "BTC"})
            journal.transition("QE-1", DISPATCHING)
            restarted = SQLiteOrderSubmissionJournal(path)
            self.assertTrue(restarted.validate_integrity())

    def test_unknown_state_is_detected_and_blocks_new_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            journal.reserve("QE-1", {"symbol": "BTC"})
            with sqlite3.connect(path) as db:
                db.execute("UPDATE order_submissions SET state='CORRUPT' WHERE client_order_id='QE-1'")
            with self.assertRaises(SubmissionJournalError):
                journal.validate_integrity()
            with self.assertRaises(SubmissionJournalError):
                journal.reserve("QE-2", {"symbol": "ETH"})

    def test_bad_digest_is_detected_before_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            journal.reserve("QE-1", {"symbol": "BTC"})
            with sqlite3.connect(path) as db:
                db.execute("UPDATE order_submissions SET payload_sha256='bad' WHERE client_order_id='QE-1'")
            with self.assertRaises(SubmissionJournalError):
                journal.transition("QE-1", DISPATCHING)

    def test_schema_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            with sqlite3.connect(path) as db:
                db.execute("ALTER TABLE order_submissions ADD COLUMN unexpected TEXT")
            with self.assertRaises(SubmissionJournalError):
                journal.validate_integrity()


if __name__ == "__main__":
    unittest.main()
