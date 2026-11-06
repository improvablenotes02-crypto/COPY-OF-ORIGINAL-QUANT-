"""Phase 299: equivalent offset timestamps normalize to identical provenance."""
from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    hash_dataset_provenance,
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


def test_equivalent_timezone_offsets_share_canonical_utc_timestamp():
    utc = _dataset("2026-11-05T10:00:00Z")
    india = _dataset("2026-11-05T15:30:00+05:30")
    pacific = _dataset("2026-11-05T02:00:00-08:00")
    assert utc.source_timestamp == india.source_timestamp == pacific.source_timestamp
    assert utc.source_timestamp == "2026-11-05T10:00:00Z"


def test_equivalent_timezone_offsets_share_provenance_fingerprint():
    utc = _dataset("2026-11-05T10:00:00Z")
    offset = _dataset("2026-11-05T15:30:00+05:30")
    assert hash_dataset_provenance((utc,)) == hash_dataset_provenance((offset,))
