import tempfile
import time
import unittest
from pathlib import Path

from core.execution.submission_journal import (
    ACKNOWLEDGED, DISPATCHING, FILLED, PARTIAL, REJECTED, UNKNOWN,
    SQLiteOrderSubmissionJournal, SubmissionJournalError,
)
from core.execution.venue_history_reconciliation import (
    VenueHistoryEvidenceError, reconcile_submission,
)


class TestVenueHistoryReconciliationPhase263(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = SQLiteOrderSubmissionJournal(Path(self.tmp.name) / "orders.db")
        self.journal.reserve("QE-263", {"symbol": "NIFTY", "qty": 1})
        self.journal.transition("QE-263", DISPATCHING)
        self.now = time.time_ns()
        self.meta = dict(
            venue="test-venue", account_id="paper-test-account",
            source="complete-order-history-v1", snapshot_as_of_ns=self.now,
            complete=True, now_ns=self.now,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def reconcile(self, orders, **kwargs):
        return reconcile_submission(
            self.journal, "QE-263", orders=orders, **(self.meta | kwargs)
        )

    def test_open_order_is_acknowledged_with_evidence(self):
        result = self.reconcile([{"client_order_id": "QE-263", "status": "open"}])
        self.assertEqual(result["state"], ACKNOWLEDGED)
        self.assertEqual(self.journal.get("QE-263")["state"], ACKNOWLEDGED)
        self.assertIn("sha256=", self.journal.get("QE-263")["detail"])

    def test_filled_order_requires_venue_record(self):
        result = self.reconcile([{"client_order_id": "QE-263", "status": "filled", "filled_size": 1, "size": 1}])
        self.assertEqual(result["state"], FILLED)

    def test_partial_fill_is_not_promoted_to_filled(self):
        result = self.reconcile([{"client_order_id": "QE-263", "status": "open", "filled_size": 1, "size": 2}])
        self.assertEqual(result["state"], PARTIAL)

    def test_rejection_is_resolved_only_from_explicit_record(self):
        result = self.reconcile([{"client_order_id": "QE-263", "status": "rejected"}])
        self.assertEqual(result["state"], REJECTED)

    def test_absence_does_not_mean_rejected(self):
        result = self.reconcile([])
        self.assertFalse(result["resolved"])
        self.assertEqual(self.journal.get("QE-263")["state"], DISPATCHING)

    def test_duplicate_matches_fail_closed(self):
        with self.assertRaises(VenueHistoryEvidenceError):
            self.reconcile([
                {"client_order_id": "QE-263", "status": "open"},
                {"client_order_id": "QE-263", "status": "filled"},
            ])
        self.assertEqual(self.journal.get("QE-263")["state"], DISPATCHING)

    def test_incomplete_or_stale_history_is_rejected(self):
        with self.assertRaises(VenueHistoryEvidenceError):
            self.reconcile([], complete=False)
        with self.assertRaises(VenueHistoryEvidenceError):
            self.reconcile([], snapshot_as_of_ns=self.now - 60_000_000_000)
        self.assertEqual(self.journal.get("QE-263")["state"], DISPATCHING)

    def test_unrecognized_venue_state_remains_unresolved(self):
        result = self.reconcile([{"client_order_id": "QE-263", "status": "mystery"}])
        self.assertFalse(result["resolved"])
        self.assertEqual(result["state"], UNKNOWN)
        self.assertEqual(self.journal.get("QE-263")["state"], DISPATCHING)

    def test_cannot_reconcile_without_reservation(self):
        with self.assertRaises(SubmissionJournalError):
            reconcile_submission(self.journal, "missing", orders=[{"client_order_id": "missing", "status": "open"}], **self.meta)


if __name__ == "__main__":
    unittest.main()
