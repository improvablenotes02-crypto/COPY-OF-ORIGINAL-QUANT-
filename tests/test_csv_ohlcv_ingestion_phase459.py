"""Phase 459: strict source-neutral historical OHLCV CSV ingestion."""
from datetime import datetime, timezone

import pytest

from core.research.acquisition.csv_ohlcv import (
    CSVHistoricalDataError,
    load_ohlcv_csv,
)


def _write(tmp_path, content):
    path = tmp_path / "bars.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_import_sorts_rows_and_hashes_normalized_ohlcv_deterministically(tmp_path):
    content = (
        "timestamp,open,high,low,close,volume,symbol\n"
        "2026-11-09T09:16:00+05:30,101,103,100,102,20,NIFTY\n"
        "2026-11-09T09:15:00+05:30,100,102,99,101,10,NIFTY\n"
    )
    dataset = load_ohlcv_csv(
        _write(tmp_path, content), symbol="NIFTY", source="broker-export",
        timeframe="1m",
    )
    assert dataset.row_count == 2
    assert dataset.bars[0].timestamp == int(
        datetime(2026, 11, 9, 3, 45, tzinfo=timezone.utc).timestamp()
    )
    assert dataset.bars[0].symbol == "NIFTY"
    assert dataset.bars[0].closed is True
    reversed_dataset = load_ohlcv_csv(
        _write(tmp_path, content.splitlines()[0] + "\n" + "\n".join(reversed(content.splitlines()[1:])) + "\n"),
        symbol="NIFTY", source="broker-export", timeframe="1m",
    )
    assert dataset.dataset_hash == reversed_dataset.dataset_hash


def test_import_requires_explicit_timezone_for_naive_timestamps(tmp_path):
    path = _write(
        tmp_path,
        "datetime,open,high,low,close,volume\n"
        "2026-11-09 09:15:00,100,101,99,100,0\n",
    )
    with pytest.raises(CSVHistoricalDataError, match="explicit source_timezone"):
        load_ohlcv_csv(path, symbol="NIFTY", source="manual-export")
    result = load_ohlcv_csv(
        path, symbol="NIFTY", source="manual-export",
        source_timezone="Asia/Kolkata",
    )
    assert result.bars[0].timestamp == int(
        datetime(2026, 11, 9, 3, 45, tzinfo=timezone.utc).timestamp()
    )


def test_numeric_timestamps_require_explicit_unit(tmp_path):
    path = _write(
        tmp_path,
        "time,o,h,l,c,v\n1772941500,100,101,99,100,1\n",
    )
    with pytest.raises(CSVHistoricalDataError, match="timestamp_unit"):
        load_ohlcv_csv(path, symbol="EURUSD", source="vendor")
    result = load_ohlcv_csv(
        path, symbol="EURUSD", source="vendor", timestamp_unit="seconds",
    )
    assert result.row_count == 1


@pytest.mark.parametrize(
    "rows, message",
    [
        ("2026-11-09T03:45:00Z,100,99,98,100,1", "inconsistent high"),
        ("2026-11-09T03:45:00Z,100,103,102,103,1", "inconsistent low"),
        ("2026-11-09T03:45:00Z,100,101,99,100,-1", "volume must be finite and non-negative"),
        ("2026-11-09T03:45:00Z,100,101,99,0,1", "close must be finite and positive"),
    ],
)
def test_import_rejects_invalid_ohlcv(tmp_path, rows, message):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n" + rows + "\n",
    )
    with pytest.raises(CSVHistoricalDataError, match=message):
        load_ohlcv_csv(path, symbol="BTCUSD", source="test")


def test_import_rejects_duplicate_timestamp_and_symbol_mismatch(tmp_path):
    duplicate = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n"
        "2026-11-09T03:45:00Z,100,101,99,100,1\n"
        "2026-11-09T03:45:00Z,100,101,99,100,2\n",
    )
    with pytest.raises(CSVHistoricalDataError, match="duplicate candle timestamp"):
        load_ohlcv_csv(duplicate, symbol="BTCUSD", source="test")

    mismatch = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume,symbol\n"
        "2026-11-09T03:45:00Z,100,101,99,100,1,ETHUSD\n",
    )
    with pytest.raises(CSVHistoricalDataError, match="symbol does not match"):
        load_ohlcv_csv(mismatch, symbol="BTCUSD", source="test")


def test_gaps_are_reported_but_never_filled(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n"
        "2026-11-09T03:45:00Z,100,101,99,100,1\n"
        "2026-11-09T03:48:00Z,101,102,100,101,1\n",
    )
    dataset = load_ohlcv_csv(
        path, symbol="NIFTY", source="broker-export", timeframe="1m",
    )
    assert dataset.row_count == 2
    assert len(dataset.gaps) == 1
    assert dataset.gaps[0].missing_intervals == 2


def test_import_enforces_row_limit_and_rejects_empty_file(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n"
        "2026-11-09T03:45:00Z,100,101,99,100,1\n"
        "2026-11-09T03:46:00Z,100,101,99,100,1\n",
    )
    with pytest.raises(CSVHistoricalDataError, match="max_rows"):
        load_ohlcv_csv(path, symbol="NIFTY", source="test", max_rows=1)
    empty = _write(tmp_path, "timestamp,open,high,low,close,volume\n")
    with pytest.raises(CSVHistoricalDataError, match="no OHLCV rows"):
        load_ohlcv_csv(empty, symbol="NIFTY", source="test")


def test_scope_provenance_defaults_unknown_and_cannot_enter_backtest(tmp_path):
    from core.research.acquisition.scope_provenance import (
        ScopeProvenanceError, validate_backtest_inputs,
    )

    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n"
        "2026-11-09T03:45:00Z,100,101,99,100,1\n",
    )
    dataset = load_ohlcv_csv(
        path, symbol="NIFTY", source="broker-export",
        venue="NSE", region="INDIA", environment="PRODUCTION",
        instrument="INDEX",
        source_timestamp="2026-11-09T04:00:00Z",
    )
    assert dataset.scope_provenance.completeness == "UNKNOWN"
    with pytest.raises(ScopeProvenanceError, match="non-complete"):
        validate_backtest_inputs((dataset.scope_provenance,))


def test_explicitly_complete_csv_scope_is_compatible_with_backtest_gate(tmp_path):
    from core.research.acquisition.scope_provenance import validate_backtest_inputs

    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n"
        "2026-11-09T03:45:00Z,100,101,99,100,1\n",
    )
    dataset = load_ohlcv_csv(
        path, symbol="NIFTY", source="broker-export",
        venue="NSE", region="INDIA", environment="PRODUCTION",
        instrument="INDEX", source_timestamp="2026-11-09T04:00:00Z",
        completeness="COMPLETE", pagination_exhausted=True,
    )
    validated = validate_backtest_inputs((dataset.scope_provenance,))
    assert validated == (dataset.scope_provenance,)
    assert dataset.scope_provenance.dataset_hash == dataset.dataset_hash


def test_scope_metadata_must_be_complete_and_explicit(tmp_path):
    path = _write(
        tmp_path,
        "timestamp,open,high,low,close,volume\n"
        "2026-11-09T03:45:00Z,100,101,99,100,1\n",
    )
    with pytest.raises(CSVHistoricalDataError, match="supplied together"):
        load_ohlcv_csv(
            path, symbol="NIFTY", source="broker-export",
            venue="NSE", region="INDIA",
        )
    with pytest.raises(CSVHistoricalDataError, match="pagination"):
        load_ohlcv_csv(
            path, symbol="NIFTY", source="broker-export",
            venue="NSE", region="INDIA", environment="PRODUCTION",
            instrument="INDEX", source_timestamp="2026-11-09T04:00:00Z",
            completeness="COMPLETE", pagination_exhausted=False,
        )
