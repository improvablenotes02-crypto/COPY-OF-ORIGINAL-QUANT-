"""
====================================================

Delta Exchange Adapter

Full Delta v2 adapter: public market data plus the
privated authenticated endpoints (wallet balances,
positions, order management) signed per Delta's HMAC-SHA256
scheme (see core/exchanges/delta/delta_auth.py).

This replaces the historical NotImplementedError stub -- the
Delta Order Executor requires every BaseExchange method to be
real.

====================================================
"""

from core.exchanges.base_exchange import BaseExchange

import time
from urllib.parse import urlencode

from core.exchanges.delta.delta_auth import DeltaSignedREST
from core.exchanges.delta.delta_products import DeltaProducts
from core.exchanges.delta.write_authority import (
    ALL_KINDS,
    OFFLINE_FALLBACK_BASE_URL,
    require_write_authority,
)


class DeltaExchange(BaseExchange):

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        rest=None,
        base_url=None,
    ):

        from config.settings import settings

        self.api_key = (
            api_key
            if api_key is not None
            else settings.API_KEY
        )

        self.api_secret = (
            api_secret
            if api_secret is not None
            else settings.API_SECRET
        )

        self.rest = (
            rest
            if rest is not None
            else DeltaSignedREST(
                api_key=self.api_key,
                api_secret=self.api_secret,
                base_url=base_url,
            )
        )

    # -------------------------------------------------

    @property
    def authenticated(self):

        return bool(
            getattr(
                self.rest,
                "authenticated",
                bool(
                    self.api_key and self.api_secret
                ),
            )
        )

    # -------------------------------------------------

    def _require_auth(self):

        if not self.authenticated:

            raise RuntimeError(
                "Delta private endpoint requires "
                "DELTA_API_KEY and DELTA_API_SECRET "
                "(config/.env)"
            )

    # -------------------------------------------------
    # Public market data
    # -------------------------------------------------

    def get_products(self):

        return DeltaProducts().download()

    # -------------------------------------------------
    # Account
    # -------------------------------------------------

    def get_balance(self):

        self._require_auth()

        return self.rest.get(
            "/v2/wallet/balances"
        )

    def get_positions(self):

        self._require_auth()

        return self.rest.get(
            "/v2/positions"
        )

    # -------------------------------------------------
    # Orders
    # -------------------------------------------------

    def place_order(self, order, *, authority=None):

        # Phase193B: the adapter write path is authorization-gated HERE, not
        # only in higher-level executors.  A direct DeltaExchange call with
        # no armed token is refused before any transport write.
        base_url = getattr(self.rest, "base_url", None) or OFFLINE_FALLBACK_BASE_URL
        require_write_authority(
            authority, base_url=base_url, endpoint="/v2/orders",
            kinds=ALL_KINDS,
        )

        self._require_auth()

        rest_post = getattr(self.rest, "post", None)

        # Phase193B: transports that enforce write authority themselves
        # (production DeltaSignedREST) receive the token here, so the
        # REST boundary independently verifies mint + binding (defense
        # in depth).  Offline test doubles without the attribute keep
        # the legacy call signature; the adapter gate above already
        # validated the token.
        if bool(getattr(self.rest, "enforce_write_authority", False)):
            return rest_post(
                "/v2/orders",
                payload=order,
                authority=authority,
            )

        return rest_post(
            "/v2/orders",
            payload=order,
        )

    def cancel_order(self, order_id, product_id=None, *, authority=None):

        base_url = getattr(self.rest, "base_url", None) or OFFLINE_FALLBACK_BASE_URL
        require_write_authority(
            authority, base_url=base_url, endpoint="/v2/orders",
            kinds=ALL_KINDS,
        )

        self._require_auth()

        # Venue-verified shape (Testnet, 2026-10-11): DELETE /v2/orders
        # with a JSON body carrying the order id plus product scope.
        # The legacy DELETE /v2/orders/{id} route does not exist on
        # the venue (404); product scope is mandatory (bare scope is
        # bad_schema), so a missing product_id fails closed here
        # instead of emitting a guaranteed-rejected request.
        if product_id is None:
            raise ValueError(
                "cancel_order requires product_id for venue scoping"
            )

        # Phase193B: pass the token down to enforcing transports, like
        # place_order (adapter already validated mint + binding).
        if bool(getattr(self.rest, "enforce_write_authority", False)):
            return self.rest.delete(
                "/v2/orders",
                payload={"id": order_id, "product_id": product_id},
                authority=authority,
            )

        return self.rest.delete(
            "/v2/orders",
            payload={"id": order_id, "product_id": product_id},
        )

    def get_order(self, order_id):

        self._require_auth()

        return self.rest.get(
            f"/v2/orders/{order_id}"
        )

    # -------------------------------------------------
    # Order-history reconciliation (read-only)
    # -------------------------------------------------

    def _read_paginated_order_records(self, endpoint, *, params, max_pages):
        """Read every cursor page; refuse to call a truncated result complete."""
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        query = dict(params)
        query["page_size"] = 50  # Delta documents a maximum of 50 for history APIs.
        cursor = None
        seen_cursors = set()
        cursor_chain = []
        records = []
        pages = 0
        while True:
            page_query = dict(query)
            if cursor is not None:
                page_query["after"] = cursor
            path = endpoint + "?" + urlencode(page_query)
            response = self.rest.get(path)
            if not isinstance(response, dict) or response.get("success") is not True:
                raise RuntimeError("Delta order-history response is not a successful object")
            rows = response.get("result")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise RuntimeError("Delta order-history response has invalid result rows")
            records.extend(rows)
            pages += 1
            meta = response.get("meta")
            if not isinstance(meta, dict) or "after" not in meta:
                raise RuntimeError("Delta order-history pagination metadata is missing explicit after cursor")
            next_cursor = meta["after"]
            if next_cursor is None:
                return records, pages, {
                    "cursor_exhausted": True,
                    "cursor_hops": len(cursor_chain),
                    "record_count": len(records),
                }
            if not isinstance(next_cursor, str) or not next_cursor.strip():
                raise RuntimeError("Delta order-history pagination after cursor is invalid")
            if next_cursor in seen_cursors or next_cursor == cursor:
                raise RuntimeError("Delta order-history pagination cursor repeated")
            if pages >= max_pages:
                raise RuntimeError("Delta order-history page limit reached; snapshot is incomplete")
            seen_cursors.add(next_cursor)
            cursor_chain.append(next_cursor)
            cursor = next_cursor

    def get_order_history_snapshot(self, *, max_pages=100):
        """Return active + closed/cancelled order records for reconciliation.

        Delta exposes active orders at GET /v2/orders and closed/cancelled
        orders at GET /v2/orders/history. Both cursor streams must terminate
        normally. The local observation timestamp is NOT an exchange-atomic
        snapshot timestamp; callers must account for concurrent order updates.
        """
        self._require_auth()
        active, active_pages, active_pagination = self._read_paginated_order_records(
            "/v2/orders", params={"state": "open"}, max_pages=max_pages
        )
        historical, history_pages, history_pagination = self._read_paginated_order_records(
            "/v2/orders/history", params={}, max_pages=max_pages
        )
        observed_at_ns = time.time_ns()
        return {
            "venue": "delta",
            "source": "delta-v2-active-and-order-history",
            "orders": active + historical,
            "complete": True,
            "snapshot_as_of_ns": observed_at_ns,
            "observation_is_exchange_atomic": False,
            "pagination": {
                "active_pages": active_pages,
                "history_pages": history_pages,
                "page_size": 50,
            },
            "pagination_evidence": {
                "active_cursor_exhausted": active_pagination["cursor_exhausted"],
                "history_cursor_exhausted": history_pagination["cursor_exhausted"],
                "active_cursor_hops": active_pagination["cursor_hops"],
                "history_cursor_hops": history_pagination["cursor_hops"],
                "active_record_count": active_pagination["record_count"],
                "history_record_count": history_pagination["record_count"],
            },
        }

    def get_fill_history_snapshot(self, *, max_pages=100):
        """Return a fully paginated, read-only Delta fills snapshot.

        This is a separate observation from order history and is not
        exchange-atomic with it. Callers must bind it to an explicit account
        scope and must not infer rejection from an order having no fills.
        """
        self._require_auth()
        fills, pages, pagination = self._read_paginated_order_records(
            "/v2/fills", params={}, max_pages=max_pages
        )
        return {
            "venue": "delta",
            "source": "delta-v2-fills",
            "fills": fills,
            "complete": True,
            "snapshot_as_of_ns": time.time_ns(),
            "observation_is_exchange_atomic": False,
            "pagination": {"pages": pages, "page_size": 50},
            "pagination_evidence": {
                "cursor_exhausted": pagination["cursor_exhausted"],
                "cursor_hops": pagination["cursor_hops"],
                "record_count": pagination["record_count"],
            },
        }

    # -------------------------------------------------
    # Product id lookup (symbol -> Delta product id)
    # -------------------------------------------------

    def get_product_id(
        self,
        symbol,
        products=None,
    ):

        data = (
            products
            if products is not None
            else self.get_products()
        )

        result = (
            data.get("result")
            if isinstance(data, dict)
            else data
        )

        for product in result or []:

            if product.get("symbol") == symbol:
                return product.get("id")

        return None
