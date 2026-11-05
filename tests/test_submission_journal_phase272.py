import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from core.execution.submission_journal import (
    SQLiteOrderSubmissionJournal, SubmissionJournalError,
)


class TestSubmissionJournalValidatedReadsPhase272(unittest.TestCase):
    def test_get_and_unresolved_return_validated_consistent_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = SQLiteOrderSubmissionJournal(Path(tmp) / "journal.sqlite3")
            journal.reserve("QE-read-1", {"symbol": "BTC"})
            journal.reserve("QE-read-2", {"symbol": "ETH"})
            record = journal.get("QE-read-1")
            self.assertEqual(record["client_order_id"], "QE-read-1")
            self.assertEqual(record["state"], "PREPARED")
            self.assertIsNone(journal.get("QE-absent"))
            rows = journal.unresolved()
            self.assertEqual(
                [row["client_order_id"] for row in rows],
                ["QE-read-1", "QE-read-2"],
            )

    def test_get_fails_closed_on_corrupt_record_even_when_reading_other_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            journal.reserve("QE-good", {"symbol": "BTC"})
            journal.reserve("QE-bad", {"symbol": "ETH"})
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE order_submissions SET state='CORRUPT' "
                    "WHERE client_order_id='QE-bad'"
                )
                db.commit()
            with self.assertRaises(SubmissionJournalError):
                journal.get("QE-good")

    def test_unresolved_fails_closed_on_corrupt_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            journal.reserve("QE-good", {"symbol": "BTC"})
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE order_submissions SET payload_sha256='bad' "
                    "WHERE client_order_id='QE-good'"
                )
                db.commit()
            with self.assertRaises(SubmissionJournalError):
                journal.unresolved()


if __name__ == "__main__":
    unittest.main()
