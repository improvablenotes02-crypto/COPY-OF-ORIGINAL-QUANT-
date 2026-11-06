"""Phase 279: bind reconciliation decisions to scoped complete snapshots."""
import tempfile
import unittest
from pathlib import Path

from core.execution.submission_journal import DISPATCHING, SQLiteOrderSubmissionJournal
from core.execution.venue_history_reconciliation import VenueHistoryEvidenceError, reconcile_submission
from core.execution.delta_submission_reconciliation import DeltaSubmissionReconciliationError, reconcile_delta_submission


class TestReconciliationEvidenceBindingPhase279(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = SQLiteOrderSubmissionJournal(Path(self.tmp.name) / "orders.db")
        self.journal.reserve("QE-279", {"symbol": "NIFTY", "qty": 2})
        self.journal.transition("QE-279", DISPATCHING)
        self.now = 1_800_000_000_000_000_000

    def tearDown(self):
        self.tmp.cleanup()

    def test_venue_record_account_mismatch_does_not_resolve(self):
        with self.assertRaisesRegex(VenueHistoryEvidenceError, "account scope mismatch"):
            reconcile_submission(self.journal, "QE-279", venue="delta", account_id="acct-a",
                source="history-v1", snapshot_as_of_ns=self.now,
                orders=[{"client_order_id":"QE-279", "status":"open", "account_id":"acct-b"}],
                complete=True, now_ns=self.now)
        self.assertEqual(self.journal.get("QE-279")["state"], DISPATCHING)

    def _delta_snapshots(self):
        return ({"venue":"delta", "source":"orders-v1", "complete":True,
                 "snapshot_as_of_ns":self.now, "orders":[{"id":501,"client_order_id":"QE-279",
                 "product_id":77,"size":"2","status":"open"}]},
                {"venue":"delta", "source":"fills-v1", "complete":True,
                 "snapshot_as_of_ns":self.now+1, "fills":[]})

    def test_delta_snapshot_account_mismatch_does_not_resolve(self):
        orders, fills = self._delta_snapshots()
        orders["account_id"] = "acct-b"
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "account scope mismatch"):
            reconcile_delta_submission(self.journal, "QE-279", account_id="acct-a",
                order_snapshot=orders, fill_snapshot=fills, now_ns=self.now+2)
        self.assertEqual(self.journal.get("QE-279")["state"], DISPATCHING)

    def test_delta_matched_order_venue_mismatch_does_not_resolve(self):
        orders, fills = self._delta_snapshots()
        orders["orders"][0]["venue"] = "other"
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "venue scope mismatch"):
            reconcile_delta_submission(self.journal, "QE-279", account_id="acct-a",
                order_snapshot=orders, fill_snapshot=fills, now_ns=self.now+2)
        self.assertEqual(self.journal.get("QE-279")["state"], DISPATCHING)

    def test_delta_matched_fill_account_mismatch_does_not_resolve(self):
        orders, fills = self._delta_snapshots()
        fills["fills"] = [{"id":"f-1", "order_id":501, "product_id":77, "size":"1", "accountId":"acct-b"}]
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "account scope mismatch"):
            reconcile_delta_submission(self.journal, "QE-279", account_id="acct-a",
                order_snapshot=orders, fill_snapshot=fills, now_ns=self.now+2)
        self.assertEqual(self.journal.get("QE-279")["state"], DISPATCHING)

    def test_evidence_binds_complete_snapshots_and_reservation_digest(self):
        orders, fills = self._delta_snapshots()
        result = reconcile_delta_submission(self.journal, "QE-279", account_id="acct-a",
            order_snapshot=orders, fill_snapshot=fills, now_ns=self.now+2)
        self.assertTrue(result["resolved"])
        self.assertEqual(len(result["evidence_sha256"]), 64)
        self.assertEqual(self.journal.get("QE-279")["state"], "ACKNOWLEDGED")


if __name__ == "__main__":
    unittest.main()
