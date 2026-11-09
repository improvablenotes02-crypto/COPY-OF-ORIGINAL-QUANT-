"""Phase 482: Flattrade candle normalization and chronology tests."""
from datetime import timezone

import pytest

from data.flattrade.candle_normalization import (
    FlattradeCandleNormalizationError,
    normalize_tpseries_rows,
)


def _row(time, *, open_="100.0", high="102.0", low="99.0", close="101.0", volume="25"):
    return {
        "time": time, "into": open_, "inth": high, "intl": low,
        "intc": close, "intv": volume,
    }


def test_tpseries_normalizer_converts_india_local_time_to_utc():
    bars = normalize_tpseries_rows(
        [_row("09-11-2026 09:15:00")],
        symbol="NSE:NIFTY-INDEX", interval_minutes=1,
    )
    assert len(bars) == 1
    assert bars[0].symbol == "NSE:NIFTY-INDEX"
    assert bars[0].source == "FLATTRADE_TPSERIES"
    assert bars[0].timestamp.tzinfo == timezone.utc
    assert bars[0].timestamp.hour == 3
    assert bars[0].timestamp.minute == 45
    assert str(bars[0].open) == "100.0"
    assert str(bars[0].volume) == "25"


def test_tpseries_normalizer_accepts_documented_slash_timestamp_variant():
    bars = normalize_tpseries_rows(
        [_row("09/11/2026 09:15:00")],
        symbol="NFO:NIFTY26NOVFUT", interval_minutes=5,
    )
    assert len(bars) == 1


def test_tpseries_normalizer_rejects_missing_volume_and_invalid_ohlc():
    with pytest.raises(FlattradeCandleNormalizationError):
        normalize_tpseries_rows(
            [{"time": "09-11-2026 09:15:00", "into": "100", "inth": "101",
              "intl": "99", "intc": "100"}],
            symbol="NFO:NIFTY", interval_minutes=1,
        )
    with pytest.raises(FlattradeCandleNormalizationError):
        normalize_tpseries_rows(
            [_row("09-11-2026 09:15:00", high="98")],
            symbol="NFO:NIFTY", interval_minutes=1,
        )


def test_tpseries_normalizer_rejects_duplicate_or_out_of_order_timestamps():
    rows = [
        _row("09-11-2026 09:16:00"),
        _row("09-11-2026 09:15:00"),
    ]
    with pytest.raises(FlattradeCandleNormalizationError, match="strictly increasing"):
        normalize_tpseries_rows(rows, symbol="NFO:NIFTY", interval_minutes=1)


@pytest.mark.parametrize("interval", [0, 2, 240, True, 1.0])
def test_tpseries_normalizer_rejects_unsupported_intervals(interval):
    with pytest.raises(FlattradeCandleNormalizationError):
        normalize_tpseries_rows(
            [_row("09-11-2026 09:15:00")],
            symbol="NFO:NIFTY", interval_minutes=interval,
        )


def test_tpseries_normalizer_rejects_unknown_time_format():
    with pytest.raises(FlattradeCandleNormalizationError):
        normalize_tpseries_rows(
            [_row("2026-11-09T09:15:00+05:30")],
            symbol="NFO:NIFTY", interval_minutes=1,
        )
