"""Phase 301: scoped portfolio replay order is canonical, not mapping-dependent."""
from types import SimpleNamespace

from backtesting.portfolio_backtester import PortfolioBacktester
from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    hash_backtest_candles,
)


def _candles(symbol, timestamp):
    return [SimpleNamespace(
        timestamp=timestamp, open=10.0, high=12.0, low=9.0,
        close=11.0, volume=100.0, closed=True, symbol=symbol,
    )]


def _scope(symbol, candles):
    digest, count = hash_backtest_candles(candles)
    return DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol=symbol, timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash=digest, row_count=count,
        completeness="COMPLETE", pagination_exhausted=True,
    )


class _RecordingEngine:
    def __init__(self, symbol, order):
        self.symbol = symbol
        self.order = order

    def run(self, bars, journal=None):
        self.order.append(self.symbol)
        return len(bars)


def _portfolio(order):
    portfolio = PortfolioBacktester(lambda symbol: (None, None))
    portfolio.engines = {
        "BTCUSD": _RecordingEngine("BTCUSD", order),
        "ETHUSD": _RecordingEngine("ETHUSD", order),
    }
    return portfolio


def _reversed_inputs():
    btc, eth = _candles("BTCUSD", 100), _candles("ETHUSD", 200)
    history = {"ETHUSD": eth, "BTCUSD": btc}
    provenance = {
        "ETHUSD": [_scope("ETHUSD", eth)],
        "BTCUSD": [_scope("BTCUSD", btc)],
    }
    return history, provenance


def test_scoped_portfolio_backtest_uses_sorted_symbol_order():
    order = []
    history, provenance = _reversed_inputs()
    _portfolio(order).run_scoped(history, provenance)
    assert order == ["BTCUSD", "ETHUSD"]


def test_evidence_scoped_portfolio_backtest_uses_same_sorted_symbol_order():
    order = []
    history, provenance = _reversed_inputs()
    outcome = _portfolio(order).run_scoped_with_evidence(history, provenance)
    assert order == ["BTCUSD", "ETHUSD"]
    assert outcome.evidence.symbols == ("BTCUSD", "ETHUSD")
