"""Read-only Flattrade authentication and enabled-exchange check."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def check_flattrade_connection(*, credential_loader=None, client_factory=None, emit=print) -> int:
    client = None
    try:
        if credential_loader is None:
            # Importing settings loads the repository-root .env without printing it.
            from config.settings import settings  # noqa: F401
            credential_loader = lambda: (
                os.getenv("FLATTRADE_USER_ID", ""),
                os.getenv("FLATTRADE_SESSION_TOKEN", ""),
            )
        user_id, session_token = credential_loader()
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("Flattrade user id is not configured")
        if not isinstance(session_token, str) or not session_token.strip():
            raise ValueError("Flattrade session token is not configured")

        if client_factory is None:
            from core.exchanges.flattrade.flattrade_rest import FlattradeReadOnlyREST
            client_factory = lambda uid, token: FlattradeReadOnlyREST(
                user_id=uid, session_token=token
            )
        client = client_factory(user_id, session_token)
        details = client.user_details()
        account_id = details.get("actid") if isinstance(details, dict) else None
        exchanges = details.get("exarr") if isinstance(details, dict) else None
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("Flattrade account details are incomplete")
        if not isinstance(exchanges, list) or any(not isinstance(x, str) for x in exchanges):
            raise ValueError("Flattrade enabled-exchange list is malformed")

        emit("Flattrade authenticated session: PASS (account identifier redacted)")
        emit("Enabled exchange segments: {}".format(len(exchanges)))
        emit("Exchange writes: NOT USED")
        return 0
    except Exception as error:
        kind = type(error).__name__
        if not isinstance(kind, str) or not kind.isidentifier():
            kind = "Exception"
        emit("Flattrade connection check: FAIL ({})".format(kind))
        emit("Credentials, session token, account identifiers and provider details are redacted.")
        return 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def main() -> int:
    return check_flattrade_connection()


if __name__ == "__main__":
    raise SystemExit(main())
