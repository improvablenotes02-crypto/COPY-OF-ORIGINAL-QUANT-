"""Phase 289/291 canonical backtester provenance and payload binding tests."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    ScopeProvenanceError,
    hash_backtest_candles,
)


def _candles(symbol="BTCUSD"):
    return [
        SimpleNamespace(timestamp=1, open=10.0, high=12.0, low=9.0,
                        close=11.0, volume=100.0, closed=True, symbol=symbol),
        SimpleNamespace(timestamp=2, open=11.0, high=13.0, low=10.0,
                        close=12.0, volume=120.0, closed=True, symbol=symbol),
    ]


def _scope(candles=None, **changes):
    candles = _candles() if candles is None else candles
    digest, count = hash_backtest_candles(candles)
    values = dict(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash=digest,
        row_count=count, completeness="COMPLETE", pagination_exhausted=True,
    )
    values.update(changes)
    return DatasetScopeProvenance(**values)


class _Harness(Backtester):
    def __init__(self):
        self.calls = []

    def run(self, candles, journal=None):
        self.calls.append((candles, journal))
        return {"executed": True, "count": len(candles)}


def test_scoped_entry_validates_payload_and_forwards_arguments():
    engine = _Harness()
    candles = _candles()
    journal = object()
    result = engine.run_scoped(candles, [_scope(candles)], journal=journal)
    assert result == {"executed": True, "count": 2}
    assert engine.calls == [(tuple(candles), journal)]


@pytest.mark.parametrize("bad_scope", [
    _scope(environment="PRODUCTION"),
    _scope(region="GLOBAL"),
    _scope(completeness="PARTIAL", pagination_exhausted=False),
])
def test_invalid_scope_is_rejected_before_any_replay(bad_scope):
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError):
        engine.run_scoped(_candles(), [_scope(), bad_scope])
    assert engine.calls == []


def test_payload_tampering_rejected_before_replay():
    engine = _Harness()
    candles = _candles()
    candles[0] = replace(candles[0], close=11.5) if hasattr(candles[0], "__dataclass_fields__") else SimpleNamespace(
        timestamp=1, open=10.0, high=12.0, low=9.0, close=11.5,
        volume=100.0, closed=True, symbol="BTCUSD")
    with pytest.raises(ScopeProvenanceError, match="hash"):
        engine.run_scoped(candles, [_scope()])
    assert engine.calls == []


def test_row_count_and_symbol_mismatch_rejected():
    engine = _Harness()
    candles = _candles()
    with pytest.raises(ScopeProvenanceError, match="row count"):
        engine.run_scoped(candles[:1], [_scope(candles)])
    other_symbol = _candles("ETHUSD")
    with pytest.raises(ScopeProvenanceError, match="symbol"):
        engine.run_scoped(other_symbol, [_scope(candles)])
    assert engine.calls == []


def test_forming_nonfinite_and_malformed_candles_rejected():
    engine = _Harness()
    candles = _candles()
    candles[0] = SimpleNamespace(timestamp=1, open=10, high=12, low=9,
                                 close=11, volume=100, closed=False, symbol="BTCUSD")
    with pytest.raises(ScopeProvenanceError, match="closed"):
        engine.run_scoped(candles, [_scope()])
    assert engine.calls == []


def test_private_account_dataset_requires_exact_scope_and_matching_payload():
    candles = _candles()
    from core.research.acquisition.scope_provenance import AccountDataIdentity
    identity = AccountDataIdentity("tenant-1", "internal-1", "provider-1")
    private = _scope(candles, data_class="PRIVATE_ACCOUNT", account=identity)
    engine = _Harness()
    assert engine.run_scoped(candles, [private])["executed"] is True


def test_missing_provenance_fails_closed_at_scoped_boundary():
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError):
        engine.run_scoped(_candles(), [])
    assert engine.calls == []
