"""Phase 294: bind scoped replay evidence to strategy/config fingerprints."""
from types import SimpleNamespace

import pytest

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    ScopeProvenanceError,
    hash_backtest_candles,
)


def _inputs():
    candles = [
        SimpleNamespace(timestamp=1, open=10.0, high=12.0, low=9.0,
                        close=11.0, volume=100.0, closed=True, symbol="BTCUSD"),
        SimpleNamespace(timestamp=2, open=11.0, high=13.0, low=10.0,
                        close=12.0, volume=120.0, closed=True, symbol="BTCUSD"),
    ]
    digest, count = hash_backtest_candles(candles)
    provenance = DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash=digest, row_count=count,
        completeness="COMPLETE", pagination_exhausted=True,
    )
    return candles, provenance


class _Harness(Backtester):
    def __init__(self):
        self.calls = 0

    def run(self, candles, journal=None):
        self.calls += 1
        return {"count": len(candles)}


def test_strategy_and_configuration_fingerprints_bind_execution_identity():
    candles, provenance = _inputs()
    engine = _Harness()
    outcome = engine.run_scoped_with_evidence(
        candles, [provenance],
        strategy_fingerprint="a" * 64,
        configuration_fingerprint="b" * 64,
        engine_fingerprint="d" * 64,
    )
    assert outcome.evidence.strategy_fingerprint == "a" * 64
    assert outcome.evidence.configuration_fingerprint == "b" * 64
    assert len(outcome.evidence.execution_fingerprint) == 64
    assert outcome.evidence.execution_fingerprint != outcome.evidence.payload_hash
    assert engine.calls == 1


def test_strategy_change_changes_execution_fingerprint_not_payload_hash():
    candles, provenance = _inputs()
    one = _Harness().run_scoped_with_evidence(
        candles, [provenance], strategy_fingerprint="a" * 64,
        configuration_fingerprint="b" * 64,
        engine_fingerprint="d" * 64,
    )
    two = _Harness().run_scoped_with_evidence(
        candles, [provenance], strategy_fingerprint="c" * 64,
        configuration_fingerprint="b" * 64,
        engine_fingerprint="d" * 64,
    )
    assert one.evidence.payload_hash == two.evidence.payload_hash
    assert one.evidence.execution_fingerprint != two.evidence.execution_fingerprint


@pytest.mark.parametrize("strategy,configuration,engine", [
    ("a" * 64, None, None),
    (None, "b" * 64, None),
    ("a" * 64, "b" * 64, None),
    ("not-a-sha256", "b" * 64, "c" * 64),
])
def test_incomplete_or_malformed_fingerprints_fail_before_replay(strategy, configuration, engine):
    candles, provenance = _inputs()
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError, match="fingerprint"):
        engine.run_scoped_with_evidence(
            candles, [provenance],
            strategy_fingerprint=strategy,
            configuration_fingerprint=configuration,
            engine_fingerprint=engine,
        )
    assert engine.calls == 0


def test_dataset_only_evidence_remains_available_without_fingerprints():
    candles, provenance = _inputs()
    outcome = _Harness().run_scoped_with_evidence(candles, [provenance])
    assert outcome.evidence.execution_fingerprint is None
    assert outcome.evidence.payload_hash
