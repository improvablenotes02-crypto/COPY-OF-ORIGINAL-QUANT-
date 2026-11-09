"""Strict environment boolean parsing regressions."""
import importlib
import pytest

import config.settings as settings_module


@pytest.mark.parametrize("value", ["treu", "1maybe", "enabled-ish"])
def test_execution_boolean_typo_fails_closed(monkeypatch, value):
    monkeypatch.setenv("LIVE_MODE", value)
    with pytest.raises(ValueError, match="Invalid LIVE_MODE"):
        importlib.reload(settings_module)


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False),
])
def test_execution_boolean_spellings_are_explicit(monkeypatch, value, expected):
    monkeypatch.setenv("PAPER_MODE", value)
    monkeypatch.delenv("LIVE_MODE", raising=False)
    module = importlib.reload(settings_module)
    assert module.settings.PAPER_MODE is expected
