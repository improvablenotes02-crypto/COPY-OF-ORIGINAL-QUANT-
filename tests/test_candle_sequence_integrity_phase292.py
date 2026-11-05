"""Phase 292: strict candle sequence integrity at scoped replay boundaries."""
from types import SimpleNamespace

import pytest

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    ScopeProvenanceError,
    hash_backtest_candles,
)


def _candles(timestamps=(100, 200, 300)):
    return [
        SimpleNamespace(
            timestamp=ts, open=10.0 + i, high=12.0 + i,
            low=9.0 + i, close=11.0 + i, volume=100.0,
            closed=True, symbol="BTCUSD",
        )
        for i, ts in enumerate(timestamps)
    ]


class _Harness(Backtester):
    def __init__(self):
        self.called = False

    def run(self, candles, journal=None):
        self.called = True
        return len(candles)


def _provenance(candles):
    from core.research.acquisition.scope_provenance import DatasetScopeProvenance
    digest, count = hash_backtest_candles(candles)
    return DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash=digest, row_count=count,
        completeness="COMPLETE", pagination_exhausted=True,
    )


@pytest.mark.parametrize("timestamps", [(100, 100, 200), (100, 300, 200), (300, 200, 100)])
def test_hash_rejects_duplicate_or_non_chronological_timestamps(timestamps):
    with pytest.raises(ScopeProvenanceError, match="timestamp"):
        hash_backtest_candles(_candles(timestamps))


@pytest.mark.parametrize("timestamps", [(100, 100, 200), (100, 300, 200)])
def test_scoped_backtest_rejects_bad_sequence_before_replay(timestamps):
    good = _candles()
    provenance = _provenance(good)
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError, match="timestamp"):
        engine.run_scoped(_candles(timestamps), [provenance])
    assert engine.called is False


def test_strictly_increasing_irregular_market_session_timestamps_are_allowed():
    candles = _candles((100, 200, 900))
    digest, count = hash_backtest_candles(candles)
    assert len(digest) == 64
    assert count == 3
