from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.exchanges.paper_data_gate_policy import validate_paper_data_gate_config
from core.runtime import realtime_engine as realtime_module
from core.runtime.realtime_engine import RealTimeEngine

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def test_legacy_compatibility_mode_allows_missing_threshold():
    assert validate_paper_data_gate_config(None) is None
    engine = RealTimeEngine(universe_manager=object())
    assert engine.market_data_max_age_seconds is None
    assert engine.market_data_gate_required is False


@pytest.mark.parametrize("threshold", [None, -1, float("nan"), float("inf"), "bad", True, False])
def test_required_policy_rejects_missing_or_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        validate_paper_data_gate_config(threshold, required=True)


def test_required_policy_normalizes_valid_threshold_and_checks_clock():
    assert validate_paper_data_gate_config("2.5", required=True, now_provider=lambda: NOW) == 2.5
    with pytest.raises(ValueError):
        validate_paper_data_gate_config(2, required=True, now_provider=NOW)
    with pytest.raises(ValueError):
        validate_paper_data_gate_config(2, required=1)


def test_realtime_engine_can_require_gate_without_breaking_default():
    with pytest.raises(ValueError, match="is required"):
        RealTimeEngine(universe_manager=object(), market_data_gate_required=True)
    engine = RealTimeEngine(
        universe_manager=object(), market_data_max_age_seconds="15", market_data_gate_required=True
    )
    assert engine.market_data_max_age_seconds == 15.0
    assert engine.market_data_gate_required is True


def test_required_policy_is_propagated_to_new_paper_runtimes(monkeypatch):
    captured = []

    class RuntimeSpy:
        def __init__(self, **kwargs):
            captured.append(kwargs)
        def retire(self):
            pass

    instrument = SimpleNamespace(symbol="BTCUSDT", exchange="DEMO", instrument_id="BTC-1")
    pipeline = SimpleNamespace(instrument=instrument)
    key = ("DEMO", "BTC-1")

    class RegistrySpy:
        def reconcile(self, instruments):
            return {"added": [key], "retained": [], "retired": []}
        def get(self, requested_key):
            assert requested_key == key
            return pipeline

    class SubscriptionSpy:
        def sync(self, instruments):
            pass

    monkeypatch.setattr(realtime_module, "PaperRuntime", RuntimeSpy)
    engine = RealTimeEngine.__new__(RealTimeEngine)
    engine.market_data_max_age_seconds = 7.0
    engine.market_data_gate_required = True
    engine.market_data_now_provider = lambda: NOW
    engine.registry = RegistrySpy()
    engine.runtimes = {}
    engine.starting_balance = 1000
    engine.journal = None
    engine.subscriptions = SubscriptionSpy()
    engine._portfolio_gate = lambda *a, **k: True
    engine._portfolio_release = lambda *a, **k: None

    class Universe:
        def eligible_instruments(self):
            return [instrument]

    engine._reconcile(Universe())
    assert captured[0]["market_data_gate_required"] is True
    assert captured[0]["market_data_max_age_seconds"] == 7.0
