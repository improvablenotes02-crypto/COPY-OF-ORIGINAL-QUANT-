"""Phase 289 tests for the canonical backtester provenance boundary."""
import pytest

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    AccountDataIdentity,
    DatasetScopeProvenance,
    ScopeProvenanceError,
)


def _scope(**changes):
    values = dict(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash="b" * 64,
        row_count=10, completeness="COMPLETE", pagination_exhausted=True,
    )
    values.update(changes)
    return DatasetScopeProvenance(**values)


class _Harness(Backtester):
    def __init__(self):
        self.calls = []

    def run(self, candles, journal=None):
        self.calls.append((candles, journal))
        return {"executed": True, "count": len(candles)}


def test_scoped_entry_validates_before_replay_and_forwards_arguments():
    engine = _Harness()
    candles = ["candle-1", "candle-2"]
    journal = object()
    result = engine.run_scoped(candles, [_scope()], journal=journal)
    assert result == {"executed": True, "count": 2}
    assert engine.calls == [(candles, journal)]


@pytest.mark.parametrize("bad_scope", [
    _scope(environment="PRODUCTION"),
    _scope(region="GLOBAL"),
    _scope(completeness="PARTIAL", pagination_exhausted=False),
])
def test_invalid_scope_is_rejected_before_any_replay(bad_scope):
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError):
        engine.run_scoped(["must-not-run"], [_scope(), bad_scope])
    assert engine.calls == []


def test_private_account_dataset_is_accepted_only_with_exact_scope():
    identity = AccountDataIdentity("tenant-1", "internal-1", "provider-1")
    private = _scope(data_class="PRIVATE_ACCOUNT", account=identity)
    engine = _Harness()
    assert engine.run_scoped(["c"], [private])["executed"] is True


def test_missing_provenance_fails_closed_at_scoped_boundary():
    engine = _Harness()
    with pytest.raises(ScopeProvenanceError):
        engine.run_scoped(["c"], [])
    assert engine.calls == []
