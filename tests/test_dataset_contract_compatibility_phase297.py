"""Phase 297: portfolio datasets must share schema and normalization versions."""
import pytest

from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    ScopeProvenanceError,
    validate_backtest_inputs,
)


def _dataset(**changes):
    values = dict(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash="a" * 64,
        row_count=10, completeness="COMPLETE", pagination_exhausted=True,
    )
    values.update(changes)
    return DatasetScopeProvenance(**values)


@pytest.mark.parametrize("change,expected", [
    ({"schema_version": "2"}, "schema version"),
    ({"normalization_version": "2"}, "normalization version"),
])
def test_cross_symbol_backtest_rejects_mixed_data_contract_versions(change, expected):
    first = _dataset(symbol="BTCUSD")
    second = _dataset(symbol="ETHUSD", **change)
    with pytest.raises(ScopeProvenanceError, match=expected):
        validate_backtest_inputs((first, second))


def test_cross_symbol_backtest_accepts_matching_data_contract_versions():
    result = validate_backtest_inputs((
        _dataset(symbol="BTCUSD"),
        _dataset(symbol="ETHUSD"),
    ))
    assert len(result) == 2
