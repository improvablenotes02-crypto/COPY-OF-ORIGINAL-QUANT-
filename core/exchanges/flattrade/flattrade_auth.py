"""Flattrade Pi API token-exchange signing contract.

This module is pure/offline groundwork. It does not perform login, store
credentials, call the token endpoint, or authorize exchange operations.
"""
from __future__ import annotations

import hashlib


TOKEN_EXCHANGE_URL = "https://authapi.flattrade.in/trade/apitoken"


class FlattradeAuthenticationInputError(ValueError):
    """A required Flattrade authentication input is absent or malformed."""


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise FlattradeAuthenticationInputError("%s must be text" % label)
    normalized = value.strip()
    if not normalized or any(ch in normalized for ch in ("\r", "\n", "\x00")):
        raise FlattradeAuthenticationInputError(
            "%s must be non-empty and contain no control line breaks" % label
        )
    return normalized


def build_token_exchange_payload(
    *, api_key: str, request_code: str, api_secret: str
) -> dict[str, str]:
    """Build the vendor-documented payload without returning the raw secret.

    The digest is SHA-256(api_key + request_code + api_secret), with the
    exact concatenation and UTF-8 encoding used by Flattrade's published
    Python token-generator example. The request code is a short-lived
    authorization artifact and must be handled as a secret by callers.
    """
    key = _required_text(api_key, "API key")
    code = _required_text(request_code, "request code")
    secret = _required_text(api_secret, "API secret")
    digest = hashlib.sha256(
        (key + code + secret).encode("utf-8")
    ).hexdigest()
    return {
        "api_key": key,
        "request_code": code,
        "api_secret": digest,
    }
