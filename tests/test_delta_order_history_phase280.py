"""Phase 280: require explicit Delta cursor exhaustion before claiming completeness."""
import unittest
from urllib.parse import parse_qs, urlsplit

from core.exchanges.delta.delta_exchange import DeltaExchange


class FakeHistoryREST:
    authenticated = True

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        parsed = urlsplit(path)
        cursor = parse_qs(parsed.query).get("after", [None])[0]
        return self.pages[(parsed.path, cursor)]


class TestDeltaPaginationExhaustionPhase280(unittest.TestCase):
    def exchange(self, pages):
        rest = FakeHistoryREST(pages)
        return DeltaExchange(api_key="test-key", api_secret="test-secret", rest=rest), rest

    def test_missing_meta_fails_closed(self):
        exchange, _ = self.exchange({
            ("/v2/orders", None): {"success": True, "result": []},
        })
        with self.assertRaisesRegex(RuntimeError, "missing explicit after cursor"):
            exchange.get_order_history_snapshot()

    def test_missing_after_field_fails_closed(self):
        exchange, _ = self.exchange({
            ("/v2/orders", None): {"success": True, "result": [], "meta": {"before": None}},
        })
        with self.assertRaisesRegex(RuntimeError, "missing explicit after cursor"):
            exchange.get_order_history_snapshot()

    def test_blank_or_non_string_cursor_fails_closed(self):
        for cursor in ("", "   ", 123):
            with self.subTest(cursor=cursor):
                exchange, _ = self.exchange({
                    ("/v2/orders", None): {"success": True, "result": [], "meta": {"after": cursor}},
                })
                with self.assertRaisesRegex(RuntimeError, "after cursor is invalid"):
                    exchange.get_order_history_snapshot()

    def test_success_flag_must_be_explicit_true(self):
        exchange, _ = self.exchange({
            ("/v2/orders", None): {"result": [], "meta": {"after": None}},
        })
        with self.assertRaisesRegex(RuntimeError, "not a successful object"):
            exchange.get_order_history_snapshot()

    def test_order_snapshot_records_cursor_exhaustion_per_stream(self):
        exchange, _ = self.exchange({
            ("/v2/orders", None): {"success": True, "result": [{"id": 1}], "meta": {"after": None}},
            ("/v2/orders/history", None): {"success": True, "result": [{"id": 2}], "meta": {"after": None}},
        })
        snapshot = exchange.get_order_history_snapshot()
        self.assertTrue(snapshot["complete"])
        self.assertTrue(snapshot["pagination"]["active_cursor_exhausted"])
        self.assertTrue(snapshot["pagination"]["history_cursor_exhausted"])
        self.assertEqual(snapshot["pagination"]["active_record_count"], 1)
        self.assertEqual(snapshot["pagination"]["history_record_count"], 1)

    def test_fill_snapshot_records_explicit_cursor_exhaustion(self):
        exchange, _ = self.exchange({
            ("/v2/fills", None): {"success": True, "result": [{"id": "f1"}], "meta": {"after": None}},
        })
        snapshot = exchange.get_fill_history_snapshot()
        self.assertTrue(snapshot["complete"])
        self.assertTrue(snapshot["pagination"]["cursor_exhausted"])
        self.assertEqual(snapshot["pagination"]["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
