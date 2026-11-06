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
        if urlsplit(path).path == "/v2/users/trading_preferences":
            return {"success": True, "result": {"user_id": 987654}}
        parsed = urlsplit(path)
        key = parsed.path
        query = parse_qs(parsed.query)
        cursor = query.get("after", [None])[0]
        return self.pages[(key, cursor)]


class TestDeltaOrderHistoryPhase264(unittest.TestCase):
    def test_collects_active_and_closed_history_pages(self):
        rest = FakeHistoryREST({
            ("/v2/orders", None): {
                "success": True, "result": [{"id": 1, "client_order_id": "c1", "status": "open"}],
                "meta": {"after": "active-next"},
            },
            ("/v2/orders", "active-next"): {
                "success": True, "result": [{"id": 2, "client_order_id": "c2", "status": "open"}],
                "meta": {"after": None},
            },
            ("/v2/orders/history", None): {
                "success": True, "result": [{"id": 3, "client_order_id": "c3", "status": "rejected"}],
                "meta": {"after": None},
            },
        })
        snapshot = DeltaExchange(api_key="key", api_secret="secret", rest=rest).get_order_history_snapshot()
        self.assertTrue(snapshot["complete"])
        self.assertFalse(snapshot["observation_is_exchange_atomic"])
        self.assertEqual([x["client_order_id"] for x in snapshot["orders"]], ["c1", "c2", "c3"])
        self.assertEqual(snapshot["pagination"], {
            "active_pages": 2, "history_pages": 1, "page_size": 50,
        })
        self.assertIn("after=active-next", rest.calls[2])
        self.assertIn("page_size=50", rest.calls[1])

    def test_cursor_cycle_fails_closed(self):
        rest = FakeHistoryREST({
            ("/v2/orders", None): {
                "success": True, "result": [], "meta": {"after": "same"},
            },
            ("/v2/orders", "same"): {
                "success": True, "result": [], "meta": {"after": "same"},
            },
        })
        with self.assertRaisesRegex(RuntimeError, "cursor repeated"):
            DeltaExchange(api_key="key", api_secret="secret", rest=rest).get_order_history_snapshot()
        self.assertFalse(any("/v2/orders/history" in call for call in rest.calls))

    def test_page_limit_never_returns_truncated_snapshot(self):
        rest = FakeHistoryREST({
            ("/v2/orders", None): {
                "success": True, "result": [], "meta": {"after": "next"},
            },
        })
        with self.assertRaisesRegex(RuntimeError, "page limit"):
            DeltaExchange(api_key="key", api_secret="secret", rest=rest).get_order_history_snapshot(max_pages=1)

    def test_malformed_page_fails_closed(self):
        rest = FakeHistoryREST({
            ("/v2/orders", None): {"success": True, "result": {"not": "a list"}},
        })
        with self.assertRaisesRegex(RuntimeError, "invalid result"):
            DeltaExchange(api_key="key", api_secret="secret", rest=rest).get_order_history_snapshot()

    def test_collects_paginated_fill_history_separately(self):
        rest = FakeHistoryREST({
            ("/v2/fills", None): {
                "success": True, "result": [{"id": "f1", "order_id": 1, "size": "1"}],
                "meta": {"after": "fills-next"},
            },
            ("/v2/fills", "fills-next"): {
                "success": True, "result": [{"id": "f2", "order_id": 1, "size": "2"}],
                "meta": {"after": None},
            },
        })
        snapshot = DeltaExchange(api_key="key", api_secret="secret", rest=rest).get_fill_history_snapshot()
        self.assertTrue(snapshot["complete"])
        self.assertFalse(snapshot["observation_is_exchange_atomic"])
        self.assertEqual([row["id"] for row in snapshot["fills"]], ["f1", "f2"])
        self.assertEqual(snapshot["pagination"], {"pages": 2, "page_size": 50})
        self.assertIn("page_size=50", rest.calls[1])
        self.assertIn("after=fills-next", rest.calls[2])

    def test_authentication_required_before_any_history_read(self):
        rest = FakeHistoryREST({})
        rest.authenticated = False
        with self.assertRaises(RuntimeError):
            DeltaExchange(api_key="", api_secret="", rest=rest).get_order_history_snapshot()
        self.assertEqual(rest.calls, [])


if __name__ == "__main__":
    unittest.main()
