"""Phase 282: bind Delta history snapshots to authenticated API-key identity."""
import unittest
from urllib.parse import urlsplit

from core.exchanges.delta.delta_exchange import DeltaExchange


class IdentityREST:
    authenticated = True

    def __init__(self, identity_response):
        self.identity_response = identity_response
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if urlsplit(path).path == "/v2/users/trading_preferences":
            return self.identity_response
        return {"success": True, "result": [], "meta": {"after": None}}


class TestDeltaAuthenticatedAccountIdentityPhase282(unittest.TestCase):
    def test_order_snapshot_carries_provider_user_id_and_provenance(self):
        rest = IdentityREST({"success": True, "result": {"user_id": 57354187}})
        snapshot = DeltaExchange(api_key="k", api_secret="s", rest=rest).get_order_history_snapshot()
        self.assertEqual(snapshot["account_id"], "57354187")
        self.assertEqual(snapshot["account_id_source"], "/v2/users/trading_preferences")
        self.assertEqual(rest.calls[0], "/v2/users/trading_preferences")

    def test_fill_snapshot_carries_provider_user_id_and_provenance(self):
        rest = IdentityREST({"success": True, "result": {"user_id": 57354187}})
        snapshot = DeltaExchange(api_key="k", api_secret="s", rest=rest).get_fill_history_snapshot()
        self.assertEqual(snapshot["account_id"], "57354187")
        self.assertEqual(snapshot["account_id_source"], "/v2/users/trading_preferences")

    def test_unsuccessful_identity_response_fails_before_history_read(self):
        rest = IdentityREST({"success": False, "result": {"user_id": 57354187}})
        with self.assertRaisesRegex(RuntimeError, "identity response is unsuccessful"):
            DeltaExchange(api_key="k", api_secret="s", rest=rest).get_order_history_snapshot()
        self.assertEqual(rest.calls, ["/v2/users/trading_preferences"])

    def test_malformed_identity_result_fails_closed(self):
        cases = [
            ({"success": True, "result": None}, "result is malformed"),
            ({"success": True, "result": []}, "result is malformed"),
            ({"success": True, "result": {"user_id": None}}, "user_id is missing or invalid"),
            ({"success": True, "result": {"user_id": True}}, "user_id is missing or invalid"),
            ({"success": True, "result": {"user_id": 0}}, "user_id is missing or invalid"),
            ({"success": True, "result": {"user_id": "57354187"}}, "user_id is missing or invalid"),
        ]
        for response, message in cases:
            with self.subTest(response=response):
                rest = IdentityREST(response)
                with self.assertRaisesRegex(RuntimeError, message):
                    DeltaExchange(api_key="k", api_secret="s", rest=rest).get_fill_history_snapshot()
                self.assertEqual(rest.calls, ["/v2/users/trading_preferences"])

    def test_identity_endpoint_is_not_used_without_authentication(self):
        rest = IdentityREST({"success": True, "result": {"user_id": 57354187}})
        rest.authenticated = False
        with self.assertRaises(RuntimeError):
            DeltaExchange(api_key="", api_secret="", rest=rest).get_order_history_snapshot()
        self.assertEqual(rest.calls, [])


if __name__ == "__main__":
    unittest.main()
