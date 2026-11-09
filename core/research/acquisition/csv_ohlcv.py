"""Strict, venue-neutral OHLCV CSV ingestion for historical research.

This importer normalizes caller-supplied exports only. It does not fetch data,
infer missing bars, authenticate a venue, or certify that an export is complete.
Naive timestamps require an explicit source timezone; numeric timestamps require
an explicit unit. Duplicate timestamps and malformed OHLCV are rejected.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.history.candle import Candle
from core.research.acquisition.scope_provenance import DatasetScopeProvenance


class CSVHistoricalDataError(ValueError):
    """Historical CSV is malformed, ambiguous, or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class CSVGap:
    previous_timestamp: int
    next_timestamp: int
    missing_intervals: int


@dataclass(frozen=True, slots=True)
class CSVHistoricalDataset:
    symbol: str
    source: str
    timeframe: str
    bars: tuple[Candle, ...]
    dataset_hash: str
    actual_start: int
    actual_end: int
    gaps: tuple[CSVGap, ...]
    scope_provenance: DatasetScopeProvenance | None = None

    @property
    def row_count(self) -> int:
        return len(self.bars)


_TIMEFRAMES = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "2h": 7200,
    "4h": 14400, "6h": 21600, "1d": 86400,
}
_ALIASES = {
    "timestamp": ("timestamp", "time", "datetime", "date_time", "open_time", "start_time", "date"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "vol", "v"),
    "symbol": ("symbol", "ticker", "instrument"),
}
_TIMESTAMP_UNITS = {
    "seconds": Decimal(1),
    "milliseconds": Decimal(1000),
    "microseconds": Decimal(1_000_000),
    "nanoseconds": Decimal(1_000_000_000),
}


def _column_map(fieldnames: list[str], explicit_timestamp_column: str | None) -> dict[str, str]:
    normalized: dict[str, list[str]] = {}
    for original in fieldnames:
        if not isinstance(original, str) or not original.strip():
            raise CSVHistoricalDataError("CSV contains an empty column name")
        key = re.sub(r"[\s-]+", "_", original.strip().lower())
        normalized.setdefault(key, []).append(original)
    if any(len(names) > 1 for names in normalized.values()):
        raise CSVHistoricalDataError("CSV contains duplicate normalized column names")

    result: dict[str, str] = {}
    for semantic, aliases in _ALIASES.items():
        if semantic == "timestamp" and explicit_timestamp_column is not None:
            wanted = re.sub(r"[\s-]+", "_", explicit_timestamp_column.strip().lower())
            matches = [name for key, names in normalized.items() if key == wanted for name in names]
        else:
            matches = [name for alias in aliases for key, names in normalized.items() if key == alias for name in names]
        if len(matches) > 1:
            raise CSVHistoricalDataError("CSV has ambiguous %s columns" % semantic)
        if matches:
            result[semantic] = matches[0]
    required = ("timestamp", "open", "high", "low", "close", "volume")
    missing = [name for name in required if name not in result]
    if missing:
        raise CSVHistoricalDataError("CSV missing required columns: %s" % ", ".join(missing))
    return result


def _decimal(name: str, raw: object, *, allow_zero: bool = False) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        raise CSVHistoricalDataError("%s must be a finite number" % name) from None
    if not value.is_finite() or (value < 0 if allow_zero else value <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise CSVHistoricalDataError("%s must be finite and %s" % (name, qualifier))
    return value


def _timestamp(
    raw: object,
    *,
    source_timezone: str | None,
    timestamp_unit: str | None,
) -> int:
    text = str(raw).strip()
    if not text:
        raise CSVHistoricalDataError("timestamp is empty")

    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        if timestamp_unit not in _TIMESTAMP_UNITS:
            raise CSVHistoricalDataError(
                "numeric timestamps require timestamp_unit (seconds/milliseconds/microseconds/nanoseconds)"
            )
        try:
            seconds = Decimal(text) / _TIMESTAMP_UNITS[timestamp_unit]
        except InvalidOperation:
            raise CSVHistoricalDataError("timestamp is invalid") from None
        if not seconds.is_finite() or seconds != seconds.to_integral_value():
            raise CSVHistoricalDataError("timestamp must resolve to a whole Unix second")
        value = int(seconds)
    else:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise CSVHistoricalDataError("timestamp must be ISO-8601 or numeric with an explicit unit") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            if not source_timezone:
                raise CSVHistoricalDataError(
                    "naive timestamps require an explicit source_timezone"
                )
            try:
                zone = ZoneInfo(source_timezone)
            except ZoneInfoNotFoundError:
                raise CSVHistoricalDataError("unknown source_timezone") from None
            first = parsed.replace(tzinfo=zone, fold=0)
            second = parsed.replace(tzinfo=zone, fold=1)
            if first.utcoffset() != second.utcoffset():
                raise CSVHistoricalDataError(
                    "ambiguous local timestamp; supply an explicit UTC offset"
                )
            localized = first
            round_trip = localized.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
            if round_trip != parsed:
                raise CSVHistoricalDataError("nonexistent local timestamp in source_timezone")
            parsed = localized
        utc_seconds = parsed.astimezone(timezone.utc).timestamp()
        if not math.isfinite(utc_seconds) or not utc_seconds.is_integer():
            raise CSVHistoricalDataError("timestamps must resolve to whole Unix seconds")
        value = int(utc_seconds)

    if value <= 0:
        raise CSVHistoricalDataError("timestamp must be a positive Unix time")
    return value


def load_ohlcv_csv(
    path: str | Path,
    *,
    symbol: str,
    source: str,
    timeframe: str = "1m",
    source_timezone: str | None = None,
    timestamp_unit: str | None = None,
    timestamp_column: str | None = None,
    expected_interval_seconds: int | None = None,
    max_rows: int = 1_000_000,
    venue: str | None = None,
    region: str | None = None,
    environment: str | None = None,
    instrument: str | None = None,
    source_timestamp: str | None = None,
    completeness: str = "UNKNOWN",
    pagination_exhausted: bool = False,
) -> CSVHistoricalDataset:
    """Load a bounded CSV, sort chronologically, validate, hash, and report gaps.

    Gaps are reported, never filled. The returned hash covers normalized
    OHLCV rows in chronological order and is stable across CSV row ordering.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise CSVHistoricalDataError("symbol is required")
    if not isinstance(source, str) or not source.strip():
        raise CSVHistoricalDataError("source is required")
    symbol = symbol.strip()
    source = source.strip()
    if timeframe not in _TIMEFRAMES:
        raise CSVHistoricalDataError("unsupported timeframe")
    interval = expected_interval_seconds if expected_interval_seconds is not None else _TIMEFRAMES[timeframe]
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise CSVHistoricalDataError("expected_interval_seconds must be a positive integer")
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows <= 0:
        raise CSVHistoricalDataError("max_rows must be a positive integer")
    if timestamp_unit is not None and timestamp_unit not in _TIMESTAMP_UNITS:
        raise CSVHistoricalDataError("unsupported timestamp_unit")

    csv_path = Path(path)
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise CSVHistoricalDataError("CSV has no header")
            columns = _column_map(reader.fieldnames, timestamp_column)
            rows: list[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
            for row_number, row in enumerate(reader, start=2):
                if row_number - 1 > max_rows:
                    raise CSVHistoricalDataError("CSV exceeds max_rows limit")
                if None in row:
                    raise CSVHistoricalDataError("row %d has extra fields" % row_number)
                timestamp = _timestamp(
                    row.get(columns["timestamp"]),
                    source_timezone=source_timezone,
                    timestamp_unit=timestamp_unit,
                )
                symbol_column = columns.get("symbol")
                row_symbol = row.get(symbol_column) if symbol_column else symbol
                if row_symbol is not None and str(row_symbol).strip() and str(row_symbol).strip() != symbol:
                    raise CSVHistoricalDataError("row %d symbol does not match requested symbol" % row_number)
                values = {
                    name: _decimal(name, row.get(columns[name]), allow_zero=(name == "volume"))
                    for name in ("open", "high", "low", "close", "volume")
                }
                if values["high"] < max(values["open"], values["close"], values["low"]):
                    raise CSVHistoricalDataError("row %d has inconsistent high" % row_number)
                if values["low"] > min(values["open"], values["close"], values["high"]):
                    raise CSVHistoricalDataError("row %d has inconsistent low" % row_number)
                rows.append((
                    timestamp, values["open"], values["high"], values["low"],
                    values["close"], values["volume"],
                ))
    except OSError as error:
        raise CSVHistoricalDataError("cannot read CSV input: %s" % type(error).__name__) from None

    if not rows:
        raise CSVHistoricalDataError("CSV contains no OHLCV rows")
    rows.sort(key=lambda item: item[0])
    for index in range(1, len(rows)):
        if rows[index][0] == rows[index - 1][0]:
            raise CSVHistoricalDataError("duplicate candle timestamp")
    canonical = [
        {
            "timestamp": ts,
            "open": str(values[0].normalize()),
            "high": str(values[1].normalize()),
            "low": str(values[2].normalize()),
            "close": str(values[3].normalize()),
            "volume": str(values[4].normalize()),
            "symbol": symbol,
            "timeframe": timeframe,
            "source": source,
        }
        for ts, *values in rows
    ]
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bars = tuple(
        Candle(
            timestamp=ts,
            open=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
            closed=True,
            symbol=symbol,
        )
        for ts, open_, high, low, close, volume in rows
    )
    gaps = []
    for previous, current in zip(rows, rows[1:]):
        difference = current[0] - previous[0]
        if difference > interval and difference % interval == 0:
            gaps.append(CSVGap(previous[0], current[0], difference // interval - 1))

    scope_fields = (venue, region, environment, instrument)
    if any(value is not None for value in scope_fields) and not all(
        isinstance(value, str) and value.strip() for value in scope_fields
    ):
        raise CSVHistoricalDataError(
            "venue, region, environment, and instrument must be supplied together"
        )
    scope = None
    if all(value is not None for value in scope_fields):
        if not isinstance(source_timestamp, str) or not source_timestamp.strip():
            raise CSVHistoricalDataError(
                "source_timestamp is required when dataset scope is supplied"
            )
        try:
            scope = DatasetScopeProvenance(
                venue=venue,
                region=region,
                environment=environment,
                instrument=instrument,
                symbol=symbol,
                timeframe=timeframe,
                data_class="PUBLIC_MARKET",
                source=source,
                source_timestamp=source_timestamp,
                schema_version="1",
                normalization_version="1",
                dataset_hash=digest,
                row_count=len(bars),
                completeness=completeness,
                pagination_exhausted=pagination_exhausted,
            )
        except ValueError as error:
            raise CSVHistoricalDataError(
                "invalid dataset scope provenance: %s" % str(error)
            ) from None
    elif completeness != "UNKNOWN" or pagination_exhausted or source_timestamp is not None:
        raise CSVHistoricalDataError(
            "completeness metadata requires complete venue scope metadata"
        )

    return CSVHistoricalDataset(
        symbol=symbol,
        source=source,
        timeframe=timeframe,
        bars=bars,
        dataset_hash=digest,
        actual_start=bars[0].timestamp,
        actual_end=bars[-1].timestamp,
        gaps=tuple(gaps),
        scope_provenance=scope,
    )
