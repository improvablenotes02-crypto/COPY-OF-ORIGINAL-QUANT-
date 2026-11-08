"""Strict HTTP framing-header validation for owner governance requests."""
import io
from email.message import Message
from types import SimpleNamespace

import pytest

from core.accounts.owner_governance_api import _empty_body, _object_body


def _handler(*, content_lengths=(), transfer_encodings=(), body=b"{}"):
    headers = Message()
    headers["Content-Type"] = "application/json"
    for value in content_lengths:
        headers.add_header("Content-Length", value)
    for value in transfer_encodings:
        headers.add_header("Transfer-Encoding", value)
    return SimpleNamespace(headers=headers, rfile=io.BytesIO(body))


@pytest.mark.parametrize("values", [("2", "2"), ("2", "3"), ("2, 2",)])
def test_post_rejects_duplicate_or_combined_content_length(values):
    with pytest.raises(ValueError, match="Content-Length"):
        _object_body(_handler(content_lengths=values))


@pytest.mark.parametrize("value", ["+2", "-1", "2.0", " 2", "2 "])
def test_post_requires_decimal_content_length_grammar(value):
    with pytest.raises(ValueError, match="Content-Length"):
        _object_body(_handler(content_lengths=(value,)))


def test_post_rejects_any_transfer_encoding_header_even_if_empty():
    with pytest.raises(ValueError, match="transfer encoding"):
        _object_body(_handler(content_lengths=("2",), transfer_encodings=("",)))


def test_get_and_delete_reject_duplicate_zero_content_lengths():
    with pytest.raises(ValueError, match="duplicate Content-Length"):
        _empty_body(_handler(content_lengths=("0", "0"), body=b""))


def test_get_and_delete_reject_transfer_encoding_header():
    with pytest.raises(ValueError, match="transfer encoding"):
        _empty_body(_handler(transfer_encodings=("chunked",), body=b""))


def test_single_valid_content_length_remains_supported():
    assert _object_body(_handler(content_lengths=("2",))) == {}
    assert _empty_body(_handler(content_lengths=("0",), body=b"")) == {}
