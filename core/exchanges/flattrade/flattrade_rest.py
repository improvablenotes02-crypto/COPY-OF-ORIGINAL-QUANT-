"""Read-only Flattrade Pi REST client.

Only account-details, symbol search, quotes, historical candles and option
chain endpoints are exposed. There are deliberately no order/modify/cancel
methods in this client.
"""
from __future__ import annotations

import json
from typing import Any


FLATTRADE_REST_BASE_URL = "https://piconnect.flattrade.in/PiConnectAPI"


class FlattradeAPIError(RuntimeError):
    """Safe adapter error without provider payload or credential material."""


class FlattradeReadOnlyREST:
    def __init__(
        self, *, user_id: str, session_token: str,
        client: Any = None, base_url: str = FLATTRADE_REST_BASE_URL,
    ):
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("Flattrade user id is required")
        if not isinstance(session_token, str) or not session_token.strip():
            raise ValueError("Flattrade session token is required")
        if base_url != FLATTRADE_REST_BASE_URL:
            raise ValueError("unverified Flattrade REST origin refused")
        self.user_id = user_id.strip()
        self.session_token = session_token.strip()
        self.base_url = base_url
        if client is None:
            import httpx
            client = httpx.Client(base_url=base_url, timeout=15.0)
        self.client = client

    def _post(self, endpoint: str, payload: dict[str, Any]):
        if endpoint not in {
            "UserDetails", "SearchScrip", "GetQuotes", "TPSeries", "GetOptionChain"
        }:
            raise ValueError("endpoint is outside the read-only allowlist")
        if not isinstance(payload, dict):
            raise ValueError("request payload must be a mapping")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        try:
            response = self.client.post(
                endpoint,
                data={"jData": body, "jKey": self.session_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as error:
            raise FlattradeAPIError(
                "Flattrade read-only REST request failed (%s)" % type(error).__name__
            ) from error

    @staticmethod
    def _require_success(response, endpoint: str):
        if not isinstance(response, dict) or response.get("stat") != "Ok":
            raise FlattradeAPIError(
                "Flattrade %s response was unsuccessful or malformed" % endpoint
            )
        return response

    def user_details(self) -> dict:
        response = self._post("UserDetails", {"uid": self.user_id})
        return self._require_success(response, "UserDetails")

    def search_scrip(self, search_text: str, exchange: str | None = None) -> list[dict]:
        if not isinstance(search_text, str) or not search_text.strip():
            raise ValueError("search text is required")
        payload = {"uid": self.user_id, "stext": search_text.strip()}
        if exchange is not None:
            if not isinstance(exchange, str) or not exchange.strip():
                raise ValueError("exchange must be non-empty text")
            payload["exch"] = exchange.strip().upper()
        response = self._require_success(self._post("SearchScrip", payload), "SearchScrip")
        values = response.get("values")
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise FlattradeAPIError("Flattrade SearchScrip result is malformed")
        return values

    def get_quotes(self, exchange: str, token: str) -> dict:
        if not isinstance(exchange, str) or not exchange.strip():
            raise ValueError("exchange is required")
        if not isinstance(token, (str, int)) or isinstance(token, bool) or not str(token).strip():
            raise ValueError("instrument token is required")
        payload = {"uid": self.user_id, "exch": exchange.strip().upper(), "token": str(token)}
        response = self._post("GetQuotes", payload)
        return self._require_success(response, "GetQuotes")

    def get_time_price_series(
        self, *, exchange: str, token: str, interval: int = 1,
        start_time: int | None = None, end_time: int | None = None,
    ) -> list[dict]:
        if not isinstance(exchange, str) or not exchange.strip():
            raise ValueError("exchange is required")
        if not isinstance(token, (str, int)) or isinstance(token, bool) or not str(token).strip():
            raise ValueError("instrument token is required")
        if interval not in (1, 3, 5, 10, 15, 30, 60, 120):
            raise ValueError("unsupported Flattrade candle interval")
        if (start_time is None) != (end_time is None):
            raise ValueError("start_time and end_time must be supplied together")
        if start_time is not None:
            if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (start_time, end_time)):
                raise ValueError("candle timestamps must be non-negative epoch seconds")
            if end_time <= start_time:
                raise ValueError("end_time must be after start_time")
        payload = {
            "uid": self.user_id,
            "exch": exchange.strip().upper(),
            "token": str(token),
            "intrv": str(interval),
        }
        if start_time is not None:
            payload["st"] = str(start_time)
            payload["et"] = str(end_time)
        response = self._post("TPSeries", payload)
        if isinstance(response, dict):
            self._require_success(response, "TPSeries")
            rows = response.get("values", [])
        elif isinstance(response, list):
            # Flattrade documents a list response for chart data; some
            # payloads place stat on the first row, others return candle rows.
            if response and isinstance(response[0], dict) and response[0].get("stat") == "Not_Ok":
                raise FlattradeAPIError("Flattrade TPSeries response was unsuccessful")
            rows = response
        else:
            raise FlattradeAPIError("Flattrade TPSeries response is malformed")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise FlattradeAPIError("Flattrade TPSeries candle rows are malformed")
        return rows

    def get_option_chain(
        self, *, exchange: str, trading_symbol: str,
        strike_price: str | float, count: int = 5,
    ) -> list[dict]:
        if not isinstance(exchange, str) or not exchange.strip():
            raise ValueError("exchange is required")
        if not isinstance(trading_symbol, str) or not trading_symbol.strip():
            raise ValueError("trading symbol is required")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
            raise ValueError("option-chain count must be between 1 and 50")
        strike = str(strike_price).strip()
        if not strike:
            raise ValueError("strike price is required")
        payload = {
            "uid": self.user_id,
            "exch": exchange.strip().upper(),
            "tsym": trading_symbol.strip(),
            "strprc": strike,
            "cnt": str(count),
        }
        response = self._require_success(self._post("GetOptionChain", payload), "GetOptionChain")
        values = response.get("values")
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise FlattradeAPIError("Flattrade option-chain result is malformed")
        return values

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
