"""Phase 481: Flattrade read-only REST request contract tests."""
import json

import pytest

from core.exchanges.flattrade.flattrade_rest import (
    FLATTRADE_REST_BASE_URL,
    FlattradeAPIError,
    FlattradeReadOnlyREST,
)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.calls = []
        self.closed = False

    def post(self, path, *, data, headers):
        self.calls.append((path, data, headers))
        return FakeResponse(self.body)

    def close(self):
        self.closed = True


def test_user_details_uses_form_encoded_jdata_and_jkey():
    transport = FakeClient({"stat": "Ok", "actid": "ACCOUNT1", "exarr": ["NSE", "NFO"]})
    api = FlattradeReadOnlyREST(user_id="USER1", session_token="synthetic-token", client=transport)
    result = api.user_details()
    assert result["stat"] == "Ok"
    path, data, headers = transport.calls[0]
    assert path == "UserDetails"
    assert data["jKey"] == "synthetic-token"
    assert json.loads(data["jData"]) == {"uid": "USER1"}
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert api.base_url == FLATTRADE_REST_BASE_URL


def test_search_quotes_and_option_chain_use_only_documented_read_endpoints():
    search_client = FakeClient({"stat": "Ok", "values": [{"exch": "NFO", "tsym": "NIFTY"}]})
    api = FlattradeReadOnlyREST(user_id="U", session_token="T", client=search_client)
    assert api.search_scrip("NIFTY", "NFO")[0]["exch"] == "NFO"
    assert json.loads(search_client.calls[0][1]["jData"]) == {
        "uid": "U", "stext": "NIFTY", "exch": "NFO"
    }

    quote_client = FakeClient({"stat": "Ok", "lp": "100.00"})
    quote_api = FlattradeReadOnlyREST(user_id="U", session_token="T", client=quote_client)
    assert quote_api.get_quotes("nfo", "123")["lp"] == "100.00"

    chain_client = FakeClient({"stat": "Ok", "values": [{"tsym": "NIFTYCE"}]})
    chain_api = FlattradeReadOnlyREST(user_id="U", session_token="T", client=chain_client)
    assert chain_api.get_option_chain(
        exchange="NFO", trading_symbol="NIFTY", strike_price=22500, count=5
    )[0]["tsym"] == "NIFTYCE"
    assert all(call[0] in ("/SearchScrip", "/GetQuotes", "/GetOptionChain") for call in (
        search_client.calls[0], quote_client.calls[0], chain_client.calls[0]
    ))


def test_time_price_series_validates_interval_and_epoch_window():
    client = FakeClient([{"time": "09-11-2026 09:15:00", "into": "100", "inth": "101"}])
    api = FlattradeReadOnlyREST(user_id="U", session_token="T", client=client)
    rows = api.get_time_price_series(
        exchange="NSE", token="22", interval=1, start_time=100, end_time=200
    )
    assert len(rows) == 1
    payload = json.loads(client.calls[0][1]["jData"])
    assert payload["st"] == "100" and payload["et"] == "200" and payload["intrv"] == "1"
    with pytest.raises(ValueError):
        api.get_time_price_series(exchange="NSE", token="22", interval=2)
    with pytest.raises(ValueError):
        api.get_time_price_series(exchange="NSE", token="22", start_time=100)


def test_invalid_provider_status_is_redacted():
    client = FakeClient({"stat": "Not_Ok", "emsg": "secret=must-not-leak"})
    api = FlattradeReadOnlyREST(user_id="U", session_token="T", client=client)
    with pytest.raises(FlattradeAPIError) as caught:
        api.user_details()
    assert "must-not-leak" not in str(caught.value)


def test_readonly_adapter_has_no_order_write_methods():
    api = FlattradeReadOnlyREST(user_id="U", session_token="T", client=FakeClient({"stat": "Ok"}))
    for method in ("place_order", "modify_order", "cancel_order", "exit_order"):
        assert not hasattr(api, method)


def test_unverified_endpoint_override_is_refused():
    with pytest.raises(ValueError):
        FlattradeReadOnlyREST(
            user_id="U", session_token="T", client=FakeClient({}),
            base_url="https://example.invalid",
        )
