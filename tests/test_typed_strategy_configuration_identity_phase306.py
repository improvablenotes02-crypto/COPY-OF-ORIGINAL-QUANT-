"""Phase 306: typed strategy/configuration identities bind execution evidence."""
from types import SimpleNamespace

import pytest

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    BacktestConfigurationIdentity,
    DatasetScopeProvenance,
    EngineBuildIdentity,
    ScopeProvenanceError,
    StrategyArtifactIdentity,
    hash_backtest_candles,
)


def _inputs():
    candles = [SimpleNamespace(
        timestamp=1, open=10.0, high=12.0, low=9.0,
        close=11.0, volume=100.0, closed=True, symbol="BTCUSD",
    )]
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


def _strategy(version="1.0.0", artifact="a"):
    return StrategyArtifactIdentity(
        strategy_id="momentum-breakout", version=version,
        source_revision="1" * 40, artifact_sha256=artifact * 64,
        parameter_schema_version="3",
    )


def _configuration(config_hash="b"):
    return BacktestConfigurationIdentity(
        configuration_version="v4",
        configuration_sha256=config_hash * 64,
        parameter_schema_version="3",
    )


def _engine():
    return EngineBuildIdentity(
        release_version="1.0.0", source_revision="2" * 40,
        artifact_sha256="c" * 64, dependency_lock_sha256="d" * 64,
        runtime_identity="cpython-3.12.16-linux-x86_64",
    )


class _Harness(Backtester):
    def __init__(self):
        self.calls = 0

    def run(self, bars, journal=None):
        self.calls += 1
        return len(bars)


def test_typed_strategy_configuration_and_engine_identities_bind_execution():
    candles, scope = _inputs()
    strategy, configuration, build = _strategy(), _configuration(), _engine()
    outcome = _Harness().run_scoped_with_evidence(
        candles, [scope],
        strategy_identity=strategy,
        configuration_identity=configuration,
        engine_build_identity=build,
    )
    assert outcome.evidence.strategy_fingerprint == strategy.fingerprint
    assert outcome.evidence.configuration_fingerprint == configuration.fingerprint
    assert outcome.evidence.engine_fingerprint == build.fingerprint
    assert outcome.evidence.verify() is True


def test_strategy_or_configuration_change_changes_execution_identity():
    candles, scope = _inputs()
    build = _engine()
    baseline = _Harness().run_scoped_with_evidence(
        candles, [scope], strategy_identity=_strategy(),
        configuration_identity=_configuration(), engine_build_identity=build,
    )
    changed_strategy = _Harness().run_scoped_with_evidence(
        candles, [scope], strategy_identity=_strategy(version="1.0.1"),
        configuration_identity=_configuration(), engine_build_identity=build,
    )
    changed_config = _Harness().run_scoped_with_evidence(
        candles, [scope], strategy_identity=_strategy(),
        configuration_identity=_configuration("e"), engine_build_identity=build,
    )
    assert baseline.evidence.payload_hash == changed_strategy.evidence.payload_hash
    assert baseline.evidence.execution_fingerprint != changed_strategy.evidence.execution_fingerprint
    assert baseline.evidence.execution_fingerprint != changed_config.evidence.execution_fingerprint


def test_conflicting_raw_strategy_or_config_fingerprint_fails_before_replay():
    candles, scope = _inputs()
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError, match="conflicts"):
        engine.run_scoped_with_evidence(
            candles, [scope], strategy_fingerprint="f" * 64,
            strategy_identity=_strategy(), configuration_identity=_configuration(),
            engine_build_identity=_engine(),
        )
    assert engine.calls == 0


@pytest.mark.parametrize("strategy_identity,configuration_identity", [
    ({"version": "1"}, _configuration()),
    (_strategy(), {"version": "v4"}),
])
def test_wrong_typed_identity_objects_fail_before_replay(strategy_identity, configuration_identity):
    candles, scope = _inputs()
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError, match="identity must be"):
        engine.run_scoped_with_evidence(
            candles, [scope], strategy_identity=strategy_identity,
            configuration_identity=configuration_identity,
            engine_build_identity=_engine(),
        )
    assert engine.calls == 0
