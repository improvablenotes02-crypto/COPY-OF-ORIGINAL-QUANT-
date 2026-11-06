import tempfile
import unittest
from pathlib import Path

from core.execution.delta_submission_reconciliation import (
    DeltaSubmissionReconciliationError,
    reconcile_delta_submission,
)
from core.execution.submission_journal import (
    ACKNOWLEDGED, CANCELLED, DISPATCHING, FILLED, PARTIAL, REJECTED,
    UNKNOWN, SQLiteOrderSubmissionJournal,
)


class TestDeltaSubmissionReconciliationPhase266(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = SQLiteOrderSubmissionJournal(Path(self.tmp.name) / "orders.db")
        self.journal.reserve("QE-266", {"symbol": "BTCUSD", "size": "3"})
        self.journal.transition("QE-266", DISPATCHING)
        self.now = 1_800_000_000_000_000_000
        self.order_snapshot = {
            "venue": "delta", "source": "delta-v2-active-and-order-history",
            "complete": True, "snapshot_as_of_ns": self.now,
            "observation_is_exchange_atomic": False,
            "orders": [{"id": 501, "client_order_id": "QE-266",
                        "product_id": 77, "size": "3", "status": "open"}],
        }
        self.fill_snapshot = {
            "venue": "delta", "source": "delta-v2-fills",
            "complete": True, "snapshot_as_of_ns": self.now + 1_000_000_000,
            "observation_is_exchange_atomic": False,
            "fills": [],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def reconcile(self, **kwargs):
        return reconcile_delta_submission(
            self.journal, "QE-266", account_id="delta-subaccount-01",
            order_snapshot=self.order_snapshot, fill_snapshot=self.fill_snapshot,
            now_ns=self.now + 2_000_000_000, **kwargs,
        )

    def test_open_order_without_fills_is_acknowledged(self):
        result = self.reconcile()
        self.assertTrue(result["resolved"])
        self.assertEqual(result["state"], ACKNOWLEDGED)
        self.assertEqual(self.journal.get("QE-266")["state"], ACKNOWLEDGED)

    def test_rejection_requires_explicit_order_record(self):
        self.order_snapshot["orders"][0]["status"] = "rejected"
        result = self.reconcile()
        self.assertEqual(result["state"], REJECTED)

    def test_partial_fill_is_confirmed_by_exact_order_id(self):
        self.fill_snapshot["fills"] = [
            {"id": "f-1", "order_id": 501, "product_id": 77, "size": "1.25"},
        ]
        result = self.reconcile()
        self.assertEqual(result["state"], PARTIAL)
        self.assertEqual(result["fill_evidence"]["filled_size"], "1.25")

    def test_full_fill_requires_complete_fill_corroboration(self):
        self.order_snapshot["orders"][0]["status"] = "filled"
        self.order_snapshot["orders"][0]["filled_size"] = "3"
        self.fill_snapshot["fills"] = [
            {"id": "f-1", "order_id": 501, "product_id": 77, "size": "1"},
            {"id": "f-2", "order_id": 501, "product_id": 77, "size": "2"},
        ]
        result = self.reconcile()
        self.assertEqual(result["state"], FILLED)

    def test_order_claiming_fill_without_fill_rows_remains_unresolved(self):
        self.order_snapshot["orders"][0]["status"] = "filled"
        result = self.reconcile()
        self.assertFalse(result["resolved"])
        self.assertEqual(result["state"], UNKNOWN)
        self.assertEqual(self.journal.get("QE-266")["state"], DISPATCHING)

    def test_rejected_order_conflicting_with_fill_remains_unresolved(self):
        self.order_snapshot["orders"][0]["status"] = "rejected"
        self.fill_snapshot["fills"] = [
            {"id": "f-1", "order_id": 501, "product_id": 77, "size": "1"},
        ]
        result = self.reconcile()
        self.assertFalse(result["resolved"])
        self.assertEqual(self.journal.get("QE-266")["state"], DISPATCHING)

    def test_order_quantity_conflict_remains_unresolved(self):
        self.order_snapshot["orders"][0]["filled_size"] = "2"
        self.fill_snapshot["fills"] = [
            {"id": "f-1", "order_id": 501, "product_id": 77, "size": "1"},
        ]
        result = self.reconcile()
        self.assertFalse(result["resolved"])
        self.assertIn("quantity conflicts", result["reason"])

    def test_cancel_after_partial_fill_preserves_cancel_state_and_fill_detail(self):
        self.order_snapshot["orders"][0]["status"] = "cancelled"
        self.fill_snapshot["fills"] = [
            {"id": "f-1", "order_id": 501, "product_id": 77, "size": "1"},
        ]
        result = self.reconcile()
        self.assertEqual(result["state"], CANCELLED)
        self.assertEqual(result["fill_evidence"]["execution_state"], "PARTIAL")

    def test_cancel_without_fills_remains_unresolved(self):
        self.order_snapshot["orders"][0]["status"] = "cancelled"
        result = self.reconcile()
        self.assertFalse(result["resolved"])
        self.assertEqual(self.journal.get("QE-266")["state"], DISPATCHING)

    def test_missing_order_is_not_rejection(self):
        self.order_snapshot["orders"] = []
        result = self.reconcile()
        self.assertEqual(result["state"], UNKNOWN)
        self.assertEqual(self.journal.get("QE-266")["state"], DISPATCHING)

    def test_duplicate_client_order_match_fails_closed(self):
        self.order_snapshot["orders"].append(dict(self.order_snapshot["orders"][0]))
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "multiple order"):
            self.reconcile()

    def test_incomplete_stale_and_skewed_snapshots_fail_closed(self):
        self.fill_snapshot["complete"] = False
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "incomplete"):
            self.reconcile()
        self.fill_snapshot["complete"] = True
        self.fill_snapshot["snapshot_as_of_ns"] = self.now - 40_000_000_000
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "stale"):
            self.reconcile()
        self.fill_snapshot["snapshot_as_of_ns"] = self.now - 20_000_000_000
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "skew"):
            self.reconcile()
        self.assertEqual(self.journal.get("QE-266")["state"], DISPATCHING)

    def test_duplicate_fill_identifiers_fail_closed(self):
        self.fill_snapshot["fills"] = [
            {"id": "f-1", "order_id": 501, "size": "1"},
            {"id": "f-1", "order_id": 501, "size": "1"},
        ]
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "duplicate fill"):
            self.reconcile()
        self.assertEqual(self.journal.get("QE-266")["state"], DISPATCHING)

    def test_missing_account_scope_is_rejected(self):
        with self.assertRaisesRegex(DeltaSubmissionReconciliationError, "account_id"):
            reconcile_delta_submission(
                self.journal, "QE-266", account_id="",
                order_snapshot=self.order_snapshot, fill_snapshot=self.fill_snapshot,
                now_ns=self.now + 2_000_000_000,
            )


if __name__ == "__main__":
    unittest.main()
