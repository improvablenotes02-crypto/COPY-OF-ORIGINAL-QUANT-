import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.execution.submission_journal import (
    ACKNOWLEDGED, DISPATCHING, PREPARED, REJECTED, UNKNOWN,
    SQLiteOrderSubmissionJournal, SubmissionJournalError,
)


class TestSubmissionJournalHealthReportPhase273(unittest.TestCase):
    def test_health_report_counts_states_and_never_authorizes_live_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            journal.reserve("QE-health-prepared", {"symbol": "BTC"})
            journal.reserve("QE-health-ack", {"symbol": "ETH"})
            journal.transition("QE-health-ack", DISPATCHING)
            journal.transition("QE-health-ack", ACKNOWLEDGED)
            journal.reserve("QE-health-rejected", {"symbol": "SOL"})
            journal.transition("QE-health-rejected", UNKNOWN)
            journal.transition("QE-health-rejected", REJECTED)

            before = journal.get("QE-health-prepared")
            report = journal.health_report()
            after = journal.get("QE-health-prepared")

            self.assertTrue(report["integrity_valid"])
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["record_count"], 3)
            self.assertEqual(report["unresolved_count"], 1)
            self.assertEqual(report["state_counts"][PREPARED], 1)
            self.assertEqual(report["state_counts"][ACKNOWLEDGED], 1)
            self.assertEqual(report["state_counts"][REJECTED], 1)
            self.assertEqual(report["state_counts"][UNKNOWN], 0)
            self.assertFalse(report["live_execution_authorized"])
            self.assertGreater(report["generated_at_ns"], 0)
            self.assertEqual(before, after)

    def test_health_report_fails_closed_on_any_corrupt_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path)
            journal.reserve("QE-health-good", {"symbol": "BTC"})
            journal.reserve("QE-health-corrupt", {"symbol": "ETH"})
            with sqlite3.connect(path) as db:
                db.execute(
                    "UPDATE order_submissions SET payload_sha256 = ? "
                    "WHERE client_order_id = ?",
                    ("bad-digest", "QE-health-corrupt"),
                )
            with self.assertRaises(SubmissionJournalError):
                journal.health_report()


if __name__ == "__main__":
    unittest.main()
