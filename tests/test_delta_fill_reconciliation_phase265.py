import unittest

from core.execution.delta_fill_reconciliation import (
    DeltaFillEvidenceError,
    summarize_delta_order_fills,
)


class TestDeltaFillReconciliationPhase265(unittest.TestCase):
    def setUp(self):
        self.order = {"id": 501, "product_id": 77, "size": "3"}
        self.meta = dict(
            venue="delta", account_id="delta-subaccount-01",
            source="delta-v2-fills", snapshot_as_of_ns=1_800_000_000_000_000_000,
            complete=True,
        )

    def summarize(self, fills, **kwargs):
        return summarize_delta_order_fills(
            self.order, fills=fills, **(self.meta | kwargs)
        )

    def test_partial_fills_are_aggregated_exactly(self):
        result = self.summarize([
            {"id": "f-1", "order_id": "501", "product_id": 77, "size": "1.25"},
            {"id": "f-2", "order_id": 501, "product_id": 77, "size": "0.75"},
            {"id": "other", "order_id": 999, "product_id": 77, "size": "9"},
        ])
        self.assertEqual(result["execution_state"], "PARTIAL")
        self.assertEqual(result["filled_size"], "2.00")
        self.assertEqual(result["fill_count"], 2)
        self.assertEqual(result["account_id"], "delta-subaccount-01")

    def test_exact_aggregate_is_filled(self):
        result = self.summarize([
            {"id": "f-1", "order_id": 501, "product_id": 77, "size": "1"},
            {"id": "f-2", "order_id": 501, "product_id": 77, "size": "2"},
        ])
        self.assertEqual(result["execution_state"], "FILLED")
        self.assertEqual(result["filled_size"], "3")

    def test_absence_is_not_rejection(self):
        result = self.summarize([{"id": "other", "order_id": 999, "size": "1"}])
        self.assertFalse(result["has_fill_evidence"])
        self.assertEqual(result["execution_state"], "NO_FILL_EVIDENCE")

    def test_duplicate_fill_id_fails_closed(self):
        with self.assertRaisesRegex(DeltaFillEvidenceError, "duplicate fill id"):
            self.summarize([
                {"id": "f-1", "order_id": 501, "size": "1"},
                {"id": "f-1", "order_id": 501, "size": "1"},
            ])

    def test_conflicting_product_scope_fails_closed(self):
        with self.assertRaisesRegex(DeltaFillEvidenceError, "conflicting product"):
            self.summarize([{"id": "f-1", "order_id": 501, "product_id": 88, "size": "1"}])

    def test_overfill_fails_closed(self):
        with self.assertRaisesRegex(DeltaFillEvidenceError, "exceeds order size"):
            self.summarize([{"id": "f-1", "order_id": 501, "size": "3.1"}])

    def test_incomplete_snapshot_fails_closed(self):
        with self.assertRaisesRegex(DeltaFillEvidenceError, "incomplete"):
            self.summarize([], complete=False)

    def test_invalid_or_missing_fill_evidence_fails_closed(self):
        with self.assertRaisesRegex(DeltaFillEvidenceError, "stable fill id"):
            self.summarize([{"order_id": 501, "size": "1"}])
        with self.assertRaisesRegex(DeltaFillEvidenceError, "positive"):
            self.summarize([{"id": "f-1", "order_id": 501, "size": "0"}])


if __name__ == "__main__":
    unittest.main()
