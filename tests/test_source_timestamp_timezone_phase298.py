"""Phase 298: source observation timestamps must carry an explicit timezone."""
import pytest

from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    ScopeProvenanceError,
)


def _dataset(source_timestamp):
    return DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp=source_timestamp, schema_version="1",
        normalization_version="1", dataset_hash="a" * 64, row_count=10,
        completeness="COMPLETE", pagination_exhausted=True,
    )


@pytest.mark.parametrize("timestamp", [
    "2026-11-05T10:00:00Z",
    "2026-11-05T15:30:00+05:30",
    "2026-11-05T02:00:00-08:00",
])
def test_timezone_aware_iso8601_source_timestamps_are_accepted(timestamp):
    assert _dataset(timestamp).source_timestamp == timestamp


@pytest.mark.parametrize("timestamp", [
    "2026-11-05T10:00:00",
    "2026-11-05 10:00:00",
    "not-a-timestamp",
    "2026-99-99T99:99:99Z",
])
def test_ambiguous_or_malformed_source_timestamps_are_rejected(timestamp):
    with pytest.raises(ScopeProvenanceError, match="timezone-aware ISO-8601"):
        _dataset(timestamp)
