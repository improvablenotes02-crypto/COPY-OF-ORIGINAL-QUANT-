"""Phase 293: immutable evidence envelopes for scoped backtest outcomes."""
from types import SimpleNamespace

import pytest

from backtesting.backtester import Backtester
from backtesting.portfolio_backtester import PortfolioBacktester
from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    ScopeProvenanceError,
    hash_backtest_candles,
)


def _candles(symbol, offset=0):
    return [
        SimpleNamespace(
            timestamp=100 + offset, open=10.0, high=12.0, low=9.0,
            close=11.0, volume=100.0, closed=True, symbol=symbol,
        ),
        SimpleNamespace(
            timestamp=200 + offset, open=11.0, high=13.0, low=10.0,
            close=12.0, volume=120.0, closed=True, symbol=symbol,
        ),
    ]


def _scope(symbol, candles=None):
    candles = _candles(symbol) if candles is None else candles
    digest, count = hash_backtest_candles(candles)
    return DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol=symbol, timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash=digest, row_count=count,
        completeness="COMPLETE", pagination_exhausted=True,
    )


class _BacktestHarness(Backtester):
    def __init__(self):
        self.calls = []

    def run(self, candles, journal=None):
        self.calls.append((candles, journal))
        return {"trades": 3, "net_pnl": 42.0}


class _Engine:
    def __init__(self):
        self.calls = []

    def run(self, candles, journal=None):
        self.calls.append(candles)
        return len(candles)


def test_single_scoped_outcome_contains_reproducible_dataset_evidence():
    candles = _candles("BTCUSD")
    provenance = _scope("BTCUSD", candles)
    engine = _BacktestHarness()
    journal = object()

    outcome = engine.run_scoped_with_evidence(candles, [provenance], journal)

    assert outcome.result == {"trades": 3, "net_pnl": 42.0}
    assert outcome.evidence.symbols == ("BTCUSD",)
    assert outcome.evidence.row_counts == (2,)
    assert outcome.evidence.dataset_provenance == (provenance,)
    assert len(outcome.evidence.payload_hash) == 64
    assert engine.calls == [(tuple(candles), journal)]


def test_single_scoped_evidence_is_deterministic_for_identical_payload():
    candles = _candles("BTCUSD")
    provenance = _scope("BTCUSD", candles)
    first = _BacktestHarness().run_scoped_with_evidence(candles, [provenance])
    second = _BacktestHarness().run_scoped_with_evidence(candles, [provenance])
    assert first.evidence.payload_hash == second.evidence.payload_hash


def test_single_scoped_evidence_rejects_tampering_before_execution():
    original = _candles("BTCUSD")
    changed = _candles("BTCUSD")
    changed[1] = SimpleNamespace(
        timestamp=200, open=11.0, high=13.0, low=10.0,
        close=12.5, volume=120.0, closed=True, symbol="BTCUSD",
    )
    engine = _BacktestHarness()
    with pytest.raises(ScopeProvenanceError, match="hash"):
        engine.run_scoped_with_evidence(changed, [_scope("BTCUSD", original)])
    assert engine.calls == []


def test_portfolio_evidence_is_symbol_sorted_and_independent_of_mapping_order():
    btc, eth = _candles("BTCUSD"), _candles("ETHUSD", offset=10)
    scopes = {"BTCUSD": [_scope("BTCUSD", btc)], "ETHUSD": [_scope("ETHUSD", eth)]}
    first = PortfolioBacktester(lambda symbol: (None, None))
    first.engines = {"BTCUSD": _Engine(), "ETHUSD": _Engine()}
    second = PortfolioBacktester(lambda symbol: (None, None))
    second.engines = {"BTCUSD": _Engine(), "ETHUSD": _Engine()}

    one = first.run_scoped_with_evidence(
        {"BTCUSD": btc, "ETHUSD": eth}, scopes
    )
    two = second.run_scoped_with_evidence(
        {"ETHUSD": eth, "BTCUSD": btc},
        {"ETHUSD": scopes["ETHUSD"], "BTCUSD": scopes["BTCUSD"]},
    )

    assert one.result == {"BTCUSD": 2, "ETHUSD": 2}
    assert one.evidence.symbols == ("BTCUSD", "ETHUSD")
    assert one.evidence.row_counts == (2, 2)
    assert one.evidence.payload_hash == two.evidence.payload_hash


def test_portfolio_evidence_rejects_bad_later_leg_before_any_engine_runs():
    btc, eth = _candles("BTCUSD"), _candles("ETHUSD", offset=10)
    changed_eth = _candles("ETHUSD", offset=10)
    changed_eth[0] = SimpleNamespace(
        timestamp=110, open=10.0, high=12.0, low=9.0,
        close=11.5, volume=100.0, closed=True, symbol="ETHUSD",
    )
    portfolio = PortfolioBacktester(lambda symbol: (None, None))
    a, b = _Engine(), _Engine()
    portfolio.engines = {"BTCUSD": a, "ETHUSD": b}
    with pytest.raises(ScopeProvenanceError, match="hash"):
        portfolio.run_scoped_with_evidence(
            {"BTCUSD": btc, "ETHUSD": changed_eth},
            {"BTCUSD": [_scope("BTCUSD", btc)], "ETHUSD": [_scope("ETHUSD", eth)]},
        )
    assert a.calls == b.calls == []
