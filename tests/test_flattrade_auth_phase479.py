"""Phase 479: Flattrade token-exchange signing contract tests."""
import hashlib
import re

import pytest

from core.exchanges.flattrade.flattrade_auth import (
    FlattradeAuthenticationInputError,
    TOKEN_EXCHANGE_URL,
    build_token_exchange_payload,
)


def test_token_exchange_payload_matches_vendor_sha256_concatenation_contract():
    payload = build_token_exchange_payload(
        api_key="APPKEY123",
        request_code="REQUESTCODE456",
        api_secret="APPSECRET789",
    )
    expected = hashlib.sha256(
        b"APPKEY123REQUESTCODE456APPSECRET789"
    ).hexdigest()
    assert payload == {
        "api_key": "APPKEY123",
        "request_code": "REQUESTCODE456",
        "api_secret": expected,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", payload["api_secret"])
    assert TOKEN_EXCHANGE_URL == "https://authapi.flattrade.in/trade/apitoken"


def test_token_exchange_payload_never_contains_raw_api_secret():
    secret = "synthetic-flattrade-secret-never-print"
    payload = build_token_exchange_payload(
        api_key="synthetic-key",
        request_code="synthetic-request-code",
        api_secret=secret,
    )
    assert secret not in repr(payload)
    assert payload["api_secret"] != secret


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key", ""),
        ("api_key", "  "),
        ("request_code", ""),
        ("request_code", "bad\ncode"),
        ("api_secret", ""),
        ("api_secret", "bad\x00secret"),
        ("api_secret", None),
    ],
)
def test_token_exchange_rejects_missing_or_control_character_input(field, value):
    values = {
        "api_key": "key",
        "request_code": "code",
        "api_secret": "secret",
    }
    values[field] = value
    with pytest.raises(FlattradeAuthenticationInputError):
        build_token_exchange_payload(**values)


def test_token_exchange_trims_outer_whitespace_without_changing_internal_bytes():
    payload = build_token_exchange_payload(
        api_key="  APPKEY  ",
        request_code=" CODE ",
        api_secret=" SECRET ",
    )
    assert payload["api_key"] == "APPKEY"
    assert payload["request_code"] == "CODE"
    assert payload["api_secret"] == hashlib.sha256(b"APPKEYCODESECRET").hexdigest()
