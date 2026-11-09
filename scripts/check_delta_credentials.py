"""Read-only check for the operator's own Delta API credentials.

This command calls one authenticated identity endpoint only. It never reads
balances, places/cancels orders, or prints credential/account values. The
signed REST transport may retry transient connection failures on that same
read-only endpoint.
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
from core.exchanges.delta.delta_auth import (
    AUTHENTICATION_FAILED,
    INVALID_API_KEY,
    INVALID_SIGNATURE,
    IP_NOT_WHITELISTED,
    PERMISSION_DENIED,
    TIMESTAMP_ERROR,
    classify_auth_error,
)
from core.exchanges.delta.delta_environments import configured_client


_FAILURE_HINTS = {
    INVALID_API_KEY: "Check the API key configured for the selected venue.",
    INVALID_SIGNATURE: "Check the matching API secret and local clock.",
    TIMESTAMP_ERROR: "Check system clock synchronization.",
    IP_NOT_WHITELISTED: "Confirm this deployment's outbound IP is allowlisted.",
    PERMISSION_DENIED: "Confirm the key permits the identity endpoint's read operation.",
    AUTHENTICATION_FAILED: (
        "Check the selected region/environment, credential status and network reachability."
    ),
}


def _safe_auth_failure_category(error) -> str:
    """Reduce a provider exception to a fixed, credential-free category."""
    try:
        response = getattr(error, "response", None)
    except Exception:
        response = None

    try:
        status = getattr(response, "status_code", None)
    except Exception:
        status = None

    code = None
    try:
        decode = getattr(response, "json", None)
        payload = decode() if callable(decode) else None
    except Exception:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("error")
        if isinstance(detail, dict):
            candidate = detail.get("code")
        elif isinstance(detail, str):
            candidate = detail
        else:
            candidate = None
        if candidate is None:
            candidate = payload.get("code")
        if isinstance(candidate, str):
            code = candidate

    return classify_auth_error(code, http_status=status)


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
        category = _safe_auth_failure_category(error)
        emit("Delta credential verification: FAIL ({})".format(category))
        emit(_FAILURE_HINTS.get(category, _FAILURE_HINTS[AUTHENTICATION_FAILED]))
        emit("Provider response and exception details are redacted.")
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
