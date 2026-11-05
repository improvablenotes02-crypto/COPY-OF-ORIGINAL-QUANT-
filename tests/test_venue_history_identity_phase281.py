"""Phase 281: preserve exact account identity during venue-history reconciliation."""
import tempfile
import unittest
from pathlib import Path

from core.execution.submission_journal import ACKNOWLEDGED, DISPATCHING, SQLiteOrderSubmissionJournal
from core.execution.venue_history_reconciliation import VenueHistoryEvidenceError, reconcile_submission


class TestVenueHistoryIdentityPhase281(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = SQLiteOrderSubmissionJournal(Path(self.tmp.name) / "orders.db")
        self.journal.reserve("QE-281", {"symbol": "NIFTY", "qty": 1})
        self.journal.transition("QE-281", DISPATCHING)
        self.now = 1_800_000_000_000_000_000

    def tearDown(self):
        self.tmp.cleanup()

    def reconcile(self, record):
        return reconcile_submission(
            self.journal, "QE-281", venue="delta", account_id="Acct-A",
            source="history-v1", snapshot_as_of_ns=self.now,
            orders=[{"client_order_id": "QE-281", "status": "open", **record}],
            complete=True, now_ns=self.now,
        )

    def test_account_identity_is_case_sensitive(self):
        with self.assertRaisesRegex(VenueHistoryEvidenceError, "account scope mismatch"):
            self.reconcile({"account_id": "acct-a"})
        self.assertEqual(self.journal.get("QE-281")["state"], DISPATCHING)

    def test_camel_case_account_alias_is_also_exact(self):
        with self.assertRaisesRegex(VenueHistoryEvidenceError, "account scope mismatch"):
            self.reconcile({"accountId": "ACCT-A"})
        self.assertEqual(self.journal.get("QE-281")["state"], DISPATCHING)

    def test_venue_name_remains_case_normalized(self):
        result = self.reconcile({"account_id": "Acct-A", "venue": "DELTA"})
        self.assertTrue(result["resolved"])
        self.assertEqual(result["state"], ACKNOWLEDGED)
        self.assertEqual(self.journal.get("QE-281")["state"], ACKNOWLEDGED)

    def test_different_venue_is_rejected_without_mutation(self):
        with self.assertRaisesRegex(VenueHistoryEvidenceError, "venue scope mismatch"):
            self.reconcile({"account_id": "Acct-A", "venue": "other"})
        self.assertEqual(self.journal.get("QE-281")["state"], DISPATCHING)


if __name__ == "__main__":
    unittest.main()
