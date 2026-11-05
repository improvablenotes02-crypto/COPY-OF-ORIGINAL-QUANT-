"""Phase 296: provenance context is part of scoped execution identity."""
from types import SimpleNamespace

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    AccountDataIdentity,
    DatasetScopeProvenance,
    hash_backtest_candles,
)


def _candles():
    return [
        SimpleNamespace(timestamp=1, open=10.0, high=12.0, low=9.0,
                        close=11.0, volume=100.0, closed=True, symbol="BTCUSD"),
        SimpleNamespace(timestamp=2, open=11.0, high=13.0, low=10.0,
                        close=12.0, volume=120.0, closed=True, symbol="BTCUSD"),
    ]


def _scope(candles, environment="SANDBOX", account=None, source="official-rest"):
    digest, count = hash_backtest_candles(candles)
    return DatasetScopeProvenance(
        venue="delta", region="INDIA", environment=environment,
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PRIVATE_ACCOUNT" if account else "PUBLIC_MARKET",
        source=source, source_timestamp="2026-11-05T10:00:00Z",
        schema_version="1", normalization_version="1",
        dataset_hash=digest, row_count=count, completeness="COMPLETE",
        pagination_exhausted=True, account=account,
    )


class _Harness(Backtester):
    def __init__(self):
        pass

    def run(self, bars, journal=None):
        return len(bars)


def _run(scope):
    candles = _candles()
    return _Harness().run_scoped_with_evidence(
        candles, [scope], strategy_fingerprint="a" * 64,
        configuration_fingerprint="b" * 64,
        engine_fingerprint="d" * 64,
    )


def test_environment_context_changes_execution_identity_for_same_candles():
    candles = _candles()
    sandbox = _run(_scope(candles, environment="SANDBOX"))
    production = _run(_scope(candles, environment="PRODUCTION"))
    assert sandbox.evidence.payload_hash == production.evidence.payload_hash
    assert sandbox.evidence.provenance_fingerprint != production.evidence.provenance_fingerprint
    assert sandbox.evidence.execution_fingerprint != production.evidence.execution_fingerprint


def test_source_identity_changes_provenance_fingerprint():
    candles = _candles()
    official = _run(_scope(candles, source="official-rest"))
    imported = _run(_scope(candles, source="verified-archive"))
    assert official.evidence.payload_hash == imported.evidence.payload_hash
    assert official.evidence.provenance_fingerprint != imported.evidence.provenance_fingerprint


def test_private_account_identity_is_bound_to_provenance_fingerprint():
    candles = _candles()
    first = AccountDataIdentity("tenant", "internal-1", "provider-1")
    second = AccountDataIdentity("tenant", "internal-2", "provider-2")
    one = _run(_scope(candles, account=first))
    two = _run(_scope(candles, account=second))
    assert one.evidence.provenance_fingerprint != two.evidence.provenance_fingerprint
    assert one.evidence.execution_fingerprint != two.evidence.execution_fingerprint


def test_complete_provenance_context_is_deterministic():
    candles = _candles()
    scope = _scope(candles)
    one, two = _run(scope), _run(scope)
    assert one.evidence.provenance_fingerprint == two.evidence.provenance_fingerprint
    assert one.evidence.execution_fingerprint == two.evidence.execution_fingerprint
    assert one.evidence.verify() is True
