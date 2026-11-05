"""Phase 304: evidence APIs accept typed engine build identity directly."""
from types import SimpleNamespace

import pytest

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    EngineBuildIdentity,
    ScopeProvenanceError,
    hash_backtest_candles,
)


def _inputs():
    candles = [
        SimpleNamespace(timestamp=1, open=10.0, high=12.0, low=9.0,
                        close=11.0, volume=100.0, closed=True, symbol="BTCUSD"),
    ]
    digest, count = hash_backtest_candles(candles)
    scope = DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash=digest, row_count=count,
        completeness="COMPLETE", pagination_exhausted=True,
    )
    return candles, scope


def _build():
    return EngineBuildIdentity(
        release_version="1.0.0",
        source_revision="a" * 40,
        artifact_sha256="b" * 64,
        dependency_lock_sha256="c" * 64,
        runtime_identity="cpython-3.12.16-linux-x86_64",
    )


class _Harness(Backtester):
    def __init__(self):
        self.calls = 0

    def run(self, bars, journal=None):
        self.calls += 1
        return len(bars)


def test_typed_engine_build_identity_is_bound_directly_to_outcome():
    candles, scope = _inputs()
    build = _build()
    engine = _Harness()
    outcome = engine.run_scoped_with_evidence(
        candles, [scope],
        strategy_fingerprint="d" * 64,
        configuration_fingerprint="e" * 64,
        engine_build_identity=build,
    )
    assert outcome.evidence.engine_fingerprint == build.fingerprint
    assert outcome.evidence.verify() is True
    assert engine.calls == 1


def test_conflicting_raw_engine_fingerprint_and_typed_identity_fail_closed():
    candles, scope = _inputs()
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError, match="conflicts"):
        engine.run_scoped_with_evidence(
            candles, [scope],
            strategy_fingerprint="d" * 64,
            configuration_fingerprint="e" * 64,
            engine_fingerprint="f" * 64,
            engine_build_identity=_build(),
        )
    assert engine.calls == 0


def test_wrong_engine_build_identity_type_fails_closed():
    candles, scope = _inputs()
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError, match="EngineBuildIdentity"):
        engine.run_scoped_with_evidence(
            candles, [scope],
            strategy_fingerprint="d" * 64,
            configuration_fingerprint="e" * 64,
            engine_build_identity={"release_version": "1.0.0"},
        )
    assert engine.calls == 0
