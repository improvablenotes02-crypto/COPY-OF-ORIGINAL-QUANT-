"""Phase 209: end-to-end regression for the canonical realtime paper path."""
from datetime import datetime, timezone
from types import SimpleNamespace

from core.history.candle import Candle
from core.runtime.paper_runtime import PaperRuntime
from core.runtime.pipeline_registry import instrument_identity_key
from core.runtime.realtime_engine import RealTimeEngine

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


class EngineSpy:
    def __init__(self):
        self.calls = []

    def run_candle(self, candle):
        self.calls.append(candle)


class SubscriptionSpy:
    def stop_all(self):
        pass

    def sync(self, instruments):
        self.last_instruments = list(instruments)


def make_candle(symbol, timestamp=None, *, closed=True, high=102):
    return Candle(
        timestamp=int(NOW.timestamp()) if timestamp is None else timestamp,
        open=100, high=high, low=99, close=101, volume=1,
        closed=closed, symbol=symbol,
    )


def make_runtime(symbol, instrument_id, max_age=5):
    instrument = SimpleNamespace(
        symbol=symbol, exchange="FIXTURE", instrument_id=instrument_id,
    )
    pipeline = SimpleNamespace(context=SimpleNamespace())
    runtime = PaperRuntime.__new__(PaperRuntime)
    runtime.instrument = instrument
    runtime.pipeline = pipeline
    runtime.journal = None
    runtime.retired = False
    runtime.market_data_max_age_seconds = max_age
    runtime.market_data_now_provider = lambda: NOW
    runtime.market_data_gate_decisions = []
    runtime.rejected_market_data_candles = 0
    runtime.engine = EngineSpy()
    return runtime


def make_engine(runtime, symbol="BTCUSDT", instrument_id="BTC-1"):
    engine = RealTimeEngine.__new__(RealTimeEngine)
    key = instrument_identity_key("FIXTURE", instrument_id)
    engine._instruments = {symbol: runtime.instrument}
    engine.runtimes = {key: runtime}
    engine.routed = 0
    engine.unrouted = 0
    engine.route_errors = 0
    engine.last_route_error = ""
    return engine


def test_canonical_realtime_path_blocks_stale_candle_before_strategy_engine():
    runtime = make_runtime("BTCUSDT", "BTC-1", max_age=5)
    engine = make_engine(runtime)
    stale = make_candle("BTCUSDT", int(NOW.timestamp()) - 60)

    engine._on_closed_candle(stale)

    assert engine.routed == 1
    assert engine.unrouted == 0
    assert runtime.engine.calls == []
    assert runtime.rejected_market_data_candles == 1
    assert "MARKET_DATA_STALE" in runtime.market_data_gate_decisions[-1].reason_codes


def test_canonical_realtime_path_delivers_fresh_candle_and_rejects_bad_followup():
    runtime = make_runtime("BTCUSDT", "BTC-1", max_age=5)
    engine = make_engine(runtime)
    fresh = make_candle("BTCUSDT")
    malformed = make_candle("BTCUSDT", high=98)

    engine._on_closed_candle(fresh)
    engine._on_closed_candle(malformed)

    assert runtime.engine.calls == [fresh]
    assert runtime.rejected_market_data_candles == 1
    assert "CANDLE_NORMALIZATION_INVALID" in runtime.market_data_gate_decisions[-1].reason_codes


def test_canonical_realtime_path_does_not_route_unknown_symbol():
    runtime = make_runtime("BTCUSDT", "BTC-1", max_age=5)
    engine = make_engine(runtime)

    engine._on_closed_candle(make_candle("ETHUSDT"))

    assert engine.unrouted == 1
    assert runtime.engine.calls == []
    assert runtime.rejected_market_data_candles == 0


def test_new_runtime_from_universe_reconcile_receives_gate_configuration(monkeypatch):
    from core.runtime import realtime_engine as realtime_module

    captured = []

    class RuntimeSpy:
        def __init__(self, **kwargs):
            captured.append(kwargs)
        def retire(self):
            pass

    monkeypatch.setattr(realtime_module, "PaperRuntime", RuntimeSpy)
    instrument = SimpleNamespace(symbol="ETHUSDT", exchange="FIXTURE", instrument_id="ETH-2")
    pipeline = SimpleNamespace(instrument=instrument)
    key = ("FIXTURE", "ETH-2")

    class RegistrySpy:
        def reconcile(self, instruments):
            return {"added": [key], "retained": [], "retired": []}
        def get(self, requested_key):
            assert requested_key == key
            return pipeline

    class Universe:
        def eligible_instruments(self):
            return [instrument]

    engine = RealTimeEngine.__new__(RealTimeEngine)
    engine.market_data_max_age_seconds = 7
    engine.market_data_now_provider = lambda: NOW
    engine.registry = RegistrySpy()
    engine.runtimes = {}
    engine.starting_balance = 1000
    engine.journal = None
    engine.subscriptions = SubscriptionSpy()
    engine._portfolio_gate = lambda order: True
    engine._portfolio_release = lambda trade: None

    engine._reconcile(Universe())

    assert len(captured) == 1
    assert captured[0]["market_data_max_age_seconds"] == 7
    assert captured[0]["market_data_now_provider"]() == NOW
    assert engine.subscriptions.last_instruments == [instrument]
