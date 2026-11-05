"""Phase 300: complete-but-empty datasets cannot enter a backtest."""
import pytest

from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    ScopeProvenanceError,
    validate_backtest_inputs,
)


def _dataset(symbol="BTCUSD", row_count=0):
    return DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol=symbol, timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash="a" * 64, row_count=row_count,
        completeness="COMPLETE", pagination_exhausted=True,
    )


def test_empty_complete_dataset_is_not_backtest_eligible():
    with pytest.raises(ScopeProvenanceError, match="zero rows"):
        validate_backtest_inputs((_dataset(),))


def test_empty_leg_rejects_entire_portfolio_before_replay_eligibility():
    valid = _dataset("ETHUSD", row_count=10)
    empty = _dataset("BTCUSD", row_count=0)
    with pytest.raises(ScopeProvenanceError, match="zero rows"):
        validate_backtest_inputs((valid, empty))


def test_nonempty_complete_dataset_remains_eligible():
    assert validate_backtest_inputs((_dataset(row_count=1),))
