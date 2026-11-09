"""Read-only end-to-end Delta REST connectivity check.

Verifies the selected personal key with the authenticated identity endpoint,
then checks public product-catalog access through the same region-pinned
REST client. Never reads funds, positions or orders and never writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def check_connection(*, client_factory=None, emit=print) -> int:
    client = None
    try:
        if client_factory is None:
            from core.exchanges.delta.delta_environments import configured_client
            client_factory = configured_client

        from config.settings import settings
        emit("Selected Delta venue: {}/{}".format(
            getattr(settings, "DELTA_REGION", "UNKNOWN"),
            getattr(settings, "DELTA_ENVIRONMENT", "UNKNOWN"),
        ))
        client = client_factory()

        identity = client._get_authenticated_account_id()
        if not isinstance(identity, str) or not identity:
            raise RuntimeError("authenticated identity response is invalid")
        emit("Authenticated identity: PASS (account identifier redacted)")

        catalog = client.get_products()
        if not isinstance(catalog, dict) or catalog.get("success") is not True:
            raise RuntimeError("public product catalog response is unsuccessful")
        products = catalog.get("result")
        if not isinstance(products, list) or not products:
            raise RuntimeError("public product catalog is empty or malformed")
        if any(not isinstance(product, dict) for product in products):
            raise RuntimeError("public product catalog contains malformed entries")

        emit("Public REST product catalog: PASS ({} products)".format(len(products)))
        emit("Exchange writes: NOT USED")
        emit("Connectivity check: PASS")
        return 0
    except Exception as error:
        exception_type = type(error).__name__
        if not isinstance(exception_type, str) or not exception_type.isidentifier():
            exception_type = "Exception"
        emit("Delta connectivity check: FAIL ({})".format(exception_type))
        emit("Provider response, account identifiers and exception details are redacted.")
        emit("Check region/environment selection, credentials and network reachability.")
        return 1
    finally:
        rest = getattr(client, "rest", None)
        session = getattr(rest, "client", None)
        close = getattr(session, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def main() -> int:
    return check_connection()


if __name__ == "__main__":
    raise SystemExit(main())
