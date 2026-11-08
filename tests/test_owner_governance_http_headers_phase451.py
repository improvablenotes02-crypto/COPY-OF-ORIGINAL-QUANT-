"""Reject ambiguous authentication and media-type headers."""
import io
from email.message import Message
from types import SimpleNamespace
import pytest
from core.accounts.owner_governance_api import _bearer, _object_body

def _handler(*, authorization=(), content_types=("application/json",), body=b"{}"):
    headers = Message()
    for value in authorization:
        headers.add_header("Authorization", value)
    for value in content_types:
        headers.add_header("Content-Type", value)
    headers.add_header("Content-Length", str(len(body)))
    return SimpleNamespace(headers=headers, rfile=io.BytesIO(body))

@pytest.mark.parametrize("values", [
    ("Bearer owner-token", "Bearer attacker-token"),
    ("Bearer owner-token", "Basic other"), (),
])
def test_bearer_requires_exactly_one_authorization_header(values):
    with pytest.raises(PermissionError, match="authorization header"):
        _bearer(_handler(authorization=values))

def test_bearer_accepts_one_valid_header():
    assert _bearer(_handler(authorization=("Bearer owner-token",))) == "owner-token"

@pytest.mark.parametrize("values", [
    (), ("application/json", "application/json"),
    ("application/json", "text/plain"),
])
def test_post_requires_exactly_one_content_type_header(values):
    with pytest.raises(ValueError, match="Content-Type"):
        _object_body(_handler(content_types=values))

def test_post_accepts_json_content_type_with_charset():
    assert _object_body(_handler(content_types=("application/json; charset=utf-8",))) == {}

@pytest.mark.parametrize("header", [
    "Bearer owner-token extra",
    "Bearer owner token",
    "Bearer owner-token,attacker-token",
    "Bearer owner-token\\t",
    "Basic owner-token",
    "Bearer",
])
def test_bearer_rejects_invalid_or_ambiguous_token_syntax(header):
    with pytest.raises(PermissionError, match="verified bearer token"):
        _bearer(_handler(authorization=(header,)))

@pytest.mark.parametrize("header", [
    "Bearer owner-token",
    "bearer owner-token",
    "Bearer  owner-token",
    "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvd25lciJ9.signature==",
])
def test_bearer_accepts_rfc6750_bearer_token_characters(header):
    assert _bearer(_handler(authorization=(header,))) == header.split()[-1]
