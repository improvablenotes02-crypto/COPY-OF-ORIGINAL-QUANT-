"""Read-only check for the operator's own Delta API credentials.

This command performs one authenticated identity request only. It never
reads balances, places/cancels orders, or prints credential/account values.
Run from the repository root after configuring the local .env file:
    python scripts/check_delta_credentials.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Support direct script execution from the repository root.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.settings import settings
from core.exchanges.delta.delta_environments import configured_client


def verify_credentials(*, client_factory=None, emit=print) -> int:
    client = None
    emit(
        "Selected Delta venue: {}/{}".format(
            getattr(settings, "DELTA_REGION", "UNKNOWN"),
            getattr(settings, "DELTA_ENVIRONMENT", "UNKNOWN"),
        )
    )
    try:
        factory = client_factory or configured_client
        client = factory()
        # This signed identity endpoint verifies the selected personal key
        # pair without reading funds or touching any order endpoint.
        identity = client._get_authenticated_account_id()
        if not isinstance(identity, str) or not identity:
            raise RuntimeError("identity response invalid")
        emit("Authenticated account identity: PASS")
        emit("Exchange writes: NOT USED")
        return 0
    except Exception as error:  # redact exception text; it may contain request data
        emit(
            "Delta credential verification: FAIL ({})".format(
                type(error).__name__
            )
        )
        emit("Details redacted. Check region, environment, key pair and read permissions.")
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
    return verify_credentials()


if __name__ == "__main__":
    raise SystemExit(main())
