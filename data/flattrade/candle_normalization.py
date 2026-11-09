"""Normalize Flattrade TPSeries rows into venue-neutral bars.

Flattrade documents candle times in India local time and fields into/inth/
intl/intc/intv. This adapter preserves the source timestamp, validates OHLCV,
and rejects duplicate or out-of-order rows. It does not infer missing data or
certify continuity across market sessions.
"""
from __future__ import annotations

from datetime import datetime
from datetime import timezone
from zoneinfo import ZoneInfo

from core.exchanges.market_data_validation import NormalizedBar


INDIA_TZ = ZoneInfo("Asia/Kolkata")
SOURCE = "FLATTRADE_TPSERIES"
TIME_FORMATS = ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S")


class FlattradeCandleNormalizationError(ValueError):
    """A vendor candle row cannot be safely normalized."""


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FlattradeCandleNormalizationError("candle time is missing")
    parsed = None
    for fmt in TIME_FORMATS:
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        raise FlattradeCandleNormalizationError("candle time format is unsupported")
    return parsed.replace(tzinfo=INDIA_TZ).astimezone(timezone.utc)


def normalize_tpseries_rows(
    rows, *, symbol: str, interval_minutes: int
) -> list[NormalizedBar]:
    """Convert documented TPSeries OHLCV fields into UTC NormalizedBar rows."""
    if not isinstance(symbol, str) or not symbol.strip():
        raise FlattradeCandleNormalizationError("canonical symbol is required")
    if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int) or interval_minutes not in (1, 3, 5, 10, 15, 30, 60, 120):
        raise FlattradeCandleNormalizationError("unsupported candle interval")
    if not isinstance(rows, (list, tuple)):
        raise FlattradeCandleNormalizationError("candle rows must be a sequence")

    normalized = []
    previous_timestamp = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise FlattradeCandleNormalizationError("candle row %d is malformed" % index)
        try:
            timestamp = _parse_timestamp(row.get("time"))
            bar = NormalizedBar(
                symbol=symbol.strip(),
                timestamp=timestamp,
                source=SOURCE,
                open=row["into"],
                high=row["inth"],
                low=row["intl"],
                close=row["intc"],
                volume=row["intv"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FlattradeCandleNormalizationError(
                "candle row %d failed validation (%s)" % (index, type(error).__name__)
            ) from None
        if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
            raise FlattradeCandleNormalizationError(
                "candle timestamps must be strictly increasing without duplicates"
            )
        normalized.append(bar)
        previous_timestamp = bar.timestamp
    return normalized
