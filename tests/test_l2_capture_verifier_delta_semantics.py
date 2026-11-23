import pytest

from scripts.verify_l2_capture_artifacts import (
    CaptureVerificationError,
    _validate_accepted_book_levels,
)


def _raw(action, size):
    return {
        "action": action,
        "b": [["100", size]],
        "a": [["101", "2"]],
    }


def test_zero_size_update_is_valid_delete_instruction():
    _validate_accepted_book_levels(_raw("update", "0"), 1)


def test_zero_size_snapshot_is_rejected():
    with pytest.raises(CaptureVerificationError, match="size must be finite and positive"):
        _validate_accepted_book_levels(_raw("snapshot", "0"), 1)


def test_negative_size_update_is_rejected():
    with pytest.raises(CaptureVerificationError, match="size must be finite and non-negative"):
        _validate_accepted_book_levels(_raw("update", "-1"), 1)


def test_nonpositive_price_is_rejected_even_for_update():
    raw = _raw("update", "0")
    raw["b"][0][0] = "0"
    with pytest.raises(CaptureVerificationError, match="price must be finite and positive"):
        _validate_accepted_book_levels(raw, 1)
