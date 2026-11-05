"""Phase 288: venue/region/environment-bound dataset provenance.

Additive contract: separate from the frozen Phase 17 manifest. This envelope
records execution domain and exact authenticated account identity for private
data. It prevents incompatible evidence being silently combined; it does not
authenticate a venue or prove source data is truthful.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_HASH = re.compile(r"^[0-9a-f]{64}$")
_REGIONS = {"INDIA", "GLOBAL"}
_ENVIRONMENTS = {"SANDBOX", "PRODUCTION"}
_DATA_CLASSES = {"PUBLIC_MARKET", "PRIVATE_ACCOUNT"}
_COMPLETENESS = {"COMPLETE", "PARTIAL", "UNKNOWN"}


class ScopeProvenanceError(ValueError):
    """Dataset provenance is missing, malformed, or incompatible."""


@dataclass(frozen=True, slots=True)
class AccountDataIdentity:
    tenant_id: str
    internal_account_id: str
    provider_account_id: str

    def __post_init__(self) -> None:
        for name in ("tenant_id", "internal_account_id", "provider_account_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ScopeProvenanceError(f"{name} is required for private account data")
            object.__setattr__(self, name, value.strip())


@dataclass(frozen=True, slots=True)
class BacktestExecutionEvidence:
    """Immutable reference from a scoped replay to its validated input datasets."""

    dataset_provenance: tuple["DatasetScopeProvenance", ...]
    symbols: tuple[str, ...]
    row_counts: tuple[int, ...]
    payload_hash: str
    provenance_fingerprint: str
    strategy_fingerprint: str | None = None
    configuration_fingerprint: str | None = None
    execution_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.dataset_provenance or not self.symbols:
            raise ScopeProvenanceError("execution evidence requires dataset provenance")
        if len(self.dataset_provenance) != len(self.symbols) or len(self.symbols) != len(self.row_counts):
            raise ScopeProvenanceError("execution evidence dimensions do not match")
        if not isinstance(self.payload_hash, str) or not _HASH.fullmatch(self.payload_hash):
            raise ScopeProvenanceError("execution evidence payload_hash must be SHA-256")
        if not isinstance(self.provenance_fingerprint, str) or not _HASH.fullmatch(self.provenance_fingerprint):
            raise ScopeProvenanceError("execution evidence provenance_fingerprint must be SHA-256")
        supplied = (self.strategy_fingerprint, self.configuration_fingerprint)
        if (supplied[0] is None) != (supplied[1] is None):
            raise ScopeProvenanceError(
                "strategy and configuration fingerprints must be supplied together"
            )
        if supplied[0] is not None and any(
            not isinstance(value, str) or not _HASH.fullmatch(value) for value in supplied
        ):
            raise ScopeProvenanceError("strategy/configuration fingerprints must be SHA-256")
        if supplied[0] is None:
            if self.execution_fingerprint is not None:
                raise ScopeProvenanceError("execution fingerprint requires strategy/configuration")
        elif not isinstance(self.execution_fingerprint, str) or not _HASH.fullmatch(self.execution_fingerprint):
            raise ScopeProvenanceError("execution_fingerprint must be SHA-256")
        self.verify()

    def verify(self) -> bool:
        """Recompute envelope consistency without needing the original candle bytes."""
        import hashlib
        import json

        if not isinstance(self.dataset_provenance, tuple):
            raise ScopeProvenanceError("execution evidence provenance must be immutable")
        if not isinstance(self.symbols, tuple) or not isinstance(self.row_counts, tuple):
            raise ScopeProvenanceError("execution evidence dimensions must be immutable tuples")
        if tuple(sorted(self.symbols)) != self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ScopeProvenanceError("execution evidence symbols must be unique and sorted")
        if any(not isinstance(record, DatasetScopeProvenance) for record in self.dataset_provenance):
            raise ScopeProvenanceError("execution evidence contains invalid provenance")
        validate_backtest_inputs(self.dataset_provenance)
        if tuple(record.symbol for record in self.dataset_provenance) != self.symbols:
            raise ScopeProvenanceError("execution evidence symbol/provenance mismatch")
        if tuple(record.row_count for record in self.dataset_provenance) != self.row_counts:
            raise ScopeProvenanceError("execution evidence row-count mismatch")
        canonical_rows = [
            {"symbol": record.symbol, "dataset_hash": record.dataset_hash,
             "row_count": record.row_count}
            for record in self.dataset_provenance
        ]
        expected_payload_hash = hashlib.sha256(
            json.dumps(canonical_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if expected_payload_hash != self.payload_hash:
            raise ScopeProvenanceError("execution evidence payload hash is inconsistent")
        expected_provenance_fingerprint = hash_dataset_provenance(self.dataset_provenance)
        if expected_provenance_fingerprint != self.provenance_fingerprint:
            raise ScopeProvenanceError("execution evidence provenance fingerprint is inconsistent")
        if self.strategy_fingerprint is None:
            if self.configuration_fingerprint is not None or self.execution_fingerprint is not None:
                raise ScopeProvenanceError("partial execution fingerprint evidence")
        else:
            expected_execution = hashlib.sha256(
                json.dumps({
                    "payload_hash": self.payload_hash,
                    "provenance_fingerprint": self.provenance_fingerprint,
                    "strategy_fingerprint": self.strategy_fingerprint,
                    "configuration_fingerprint": self.configuration_fingerprint,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if expected_execution != self.execution_fingerprint:
                raise ScopeProvenanceError("execution fingerprint is inconsistent")
        return True


@dataclass(frozen=True, slots=True)
class ScopedBacktestOutcome:
    """Result plus immutable dataset identity evidence; does not imply profitability."""

    result: object
    evidence: BacktestExecutionEvidence


@dataclass(frozen=True, slots=True)
class DatasetScopeProvenance:
    venue: str
    region: str
    environment: str
    instrument: str
    symbol: str
    timeframe: str
    data_class: str
    source: str
    source_timestamp: str
    schema_version: str
    normalization_version: str
    dataset_hash: str
    row_count: int
    completeness: str
    pagination_exhausted: bool
    account: AccountDataIdentity | None = None

    def __post_init__(self) -> None:
        for name in ("venue", "instrument", "symbol", "timeframe", "source",
                     "source_timestamp", "schema_version", "normalization_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ScopeProvenanceError(f"{name} is required")
            object.__setattr__(self, name, value.strip())
        from datetime import datetime, timezone
        try:
            parsed_source_timestamp = datetime.fromisoformat(
                self.source_timestamp.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ScopeProvenanceError(
                "source_timestamp must be timezone-aware ISO-8601"
            ) from exc
        if parsed_source_timestamp.tzinfo is None or parsed_source_timestamp.utcoffset() is None:
            raise ScopeProvenanceError(
                "source_timestamp must be timezone-aware ISO-8601"
            )
        canonical_source_timestamp = (
            parsed_source_timestamp.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        object.__setattr__(self, "source_timestamp", canonical_source_timestamp)
        region = str(self.region).strip().upper()
        environment = str(self.environment).strip().upper()
        data_class = str(self.data_class).strip().upper()
        completeness = str(self.completeness).strip().upper()
        if region not in _REGIONS:
            raise ScopeProvenanceError("unsupported region")
        if environment not in _ENVIRONMENTS:
            raise ScopeProvenanceError("unsupported environment")
        if data_class not in _DATA_CLASSES:
            raise ScopeProvenanceError("unsupported data_class")
        if completeness not in _COMPLETENESS:
            raise ScopeProvenanceError("unsupported completeness")
        if not isinstance(self.dataset_hash, str) or not _HASH.fullmatch(self.dataset_hash):
            raise ScopeProvenanceError("dataset_hash must be a lowercase SHA-256 hex digest")
        if isinstance(self.row_count, bool) or not isinstance(self.row_count, int) or self.row_count < 0:
            raise ScopeProvenanceError("row_count must be a non-negative integer")
        if not isinstance(self.pagination_exhausted, bool):
            raise ScopeProvenanceError("pagination_exhausted must be boolean")
        if completeness == "COMPLETE" and not self.pagination_exhausted:
            raise ScopeProvenanceError("complete dataset requires exhausted pagination evidence")
        if completeness == "PARTIAL" and self.pagination_exhausted:
            raise ScopeProvenanceError("partial dataset cannot claim exhausted pagination")
        if data_class == "PRIVATE_ACCOUNT" and not isinstance(self.account, AccountDataIdentity):
            raise ScopeProvenanceError("private account data requires exact account identity")
        if data_class == "PUBLIC_MARKET" and self.account is not None:
            raise ScopeProvenanceError("public market data must not carry private account identity")
        object.__setattr__(self, "region", region)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "data_class", data_class)
        object.__setattr__(self, "completeness", completeness)


def validate_backtest_inputs(datasets: Iterable[DatasetScopeProvenance]) -> tuple[DatasetScopeProvenance, ...]:
    """Require complete, mutually compatible datasets for one backtest."""
    items = tuple(datasets)
    if not items:
        raise ScopeProvenanceError("backtest requires at least one provenance record")
    if any(not isinstance(item, DatasetScopeProvenance) for item in items):
        raise ScopeProvenanceError("every input requires validated dataset provenance")
    first = items[0]
    if first.completeness != "COMPLETE":
        raise ScopeProvenanceError("backtest rejects non-complete dataset")
    for item in items[1:]:
        if item.completeness != "COMPLETE":
            raise ScopeProvenanceError("backtest rejects non-complete dataset")
        if (item.venue, item.region, item.environment) != (
            first.venue, first.region, first.environment
        ):
            raise ScopeProvenanceError("venue, region, or environment mismatch")
        if item.data_class != first.data_class:
            raise ScopeProvenanceError("public and private datasets cannot be mixed")
        if item.schema_version != first.schema_version:
            raise ScopeProvenanceError("dataset schema version mismatch")
        if item.normalization_version != first.normalization_version:
            raise ScopeProvenanceError("dataset normalization version mismatch")
        if item.data_class == "PRIVATE_ACCOUNT" and item.account != first.account:
            raise ScopeProvenanceError("private account identity mismatch")
    return items

# Phase 296 — canonicalize complete venue/account/data provenance.
def hash_dataset_provenance(datasets: Iterable[DatasetScopeProvenance]) -> str:
    """Hash all scope metadata in a stable, symbol-sorted representation."""
    import hashlib
    import json

    records = validate_backtest_inputs(datasets)
    rows = []
    for record in sorted(records, key=lambda item: item.symbol):
        account = None
        if record.account is not None:
            account = {
                "tenant_id": record.account.tenant_id,
                "internal_account_id": record.account.internal_account_id,
                "provider_account_id": record.account.provider_account_id,
            }
        rows.append({
            "venue": record.venue,
            "region": record.region,
            "environment": record.environment,
            "instrument": record.instrument,
            "symbol": record.symbol,
            "timeframe": record.timeframe,
            "data_class": record.data_class,
            "source": record.source,
            "source_timestamp": record.source_timestamp,
            "schema_version": record.schema_version,
            "normalization_version": record.normalization_version,
            "dataset_hash": record.dataset_hash,
            "row_count": record.row_count,
            "completeness": record.completeness,
            "pagination_exhausted": record.pagination_exhausted,
            "account": account,
        })
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# Phase 291 — bind the replay payload to the declared dataset digest.
def hash_backtest_candles(candles: Iterable[object]) -> tuple[str, int]:
    """Hash canonical OHLCV rows using the frozen Phase 11G JSON/SHA-256 rule.

    Only closed, structurally valid candles are admitted. Candle symbol may be
    empty for legacy historical Candle objects; a populated symbol is checked
    against the provenance record by the caller.
    """
    import hashlib
    import json
    import math

    rows = []
    previous_timestamp = None
    for index, candle in enumerate(candles):
        try:
            timestamp = candle.timestamp
            values = {
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": float(candle.volume),
            }
            closed = getattr(candle, "closed", True)
            symbol = getattr(candle, "symbol", "")
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise ScopeProvenanceError(
                f"candle {index} is missing canonical OHLCV fields"
            ) from exc
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise ScopeProvenanceError(f"candle {index} timestamp must be an integer")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ScopeProvenanceError(
                f"candle {index} timestamp is duplicate or out of chronological order"
            )
        previous_timestamp = timestamp
        if not isinstance(closed, bool) or not closed:
            raise ScopeProvenanceError(f"candle {index} is not confirmed closed")
        if not isinstance(symbol, str):
            raise ScopeProvenanceError(f"candle {index} symbol must be a string")
        if any(not math.isfinite(value) for value in values.values()):
            raise ScopeProvenanceError(f"candle {index} contains non-finite OHLCV")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ScopeProvenanceError(f"candle {index} has invalid high")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ScopeProvenanceError(f"candle {index} has invalid low")
        if values["volume"] < 0:
            raise ScopeProvenanceError(f"candle {index} has negative volume")
        rows.append({
            "timestamp": timestamp,
            "open": values["open"],
            "high": values["high"],
            "low": values["low"],
            "close": values["close"],
            "volume": values["volume"],
            "closed": closed,
            "symbol": symbol,
        })
    blob = json.dumps(rows, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest(), len(rows)


def validate_candle_payload(candles: Iterable[object],
                            datasets: Iterable[DatasetScopeProvenance]):
    """Return a materialized replay payload only when bytes match provenance."""
    items = validate_backtest_inputs(datasets)
    payload = tuple(candles)
    digest, count = hash_backtest_candles(payload)
    if len(items) != 1:
        raise ScopeProvenanceError(
            "single-symbol backtest requires exactly one dataset provenance record"
        )
    record = items[0]
    if count != record.row_count:
        raise ScopeProvenanceError("candle row count does not match provenance")
    for index, candle in enumerate(payload):
        symbol = getattr(candle, "symbol", "")
        if symbol and symbol != record.symbol:
            raise ScopeProvenanceError(
                f"candle {index} symbol does not match dataset provenance"
            )
    if digest != record.dataset_hash:
        raise ScopeProvenanceError("candle payload hash does not match provenance")
    return payload


# Phase 293 — immutable scoped replay execution evidence.
def build_backtest_execution_evidence(
    datasets: Iterable[DatasetScopeProvenance],
    candles_by_symbol: dict[str, Iterable[object]],
    strategy_fingerprint: str | None = None,
    configuration_fingerprint: str | None = None,
) -> BacktestExecutionEvidence:
    """Validate every input leg and produce a deterministic replay evidence ID."""
    import hashlib
    import json

    records = validate_backtest_inputs(datasets)
    if not isinstance(candles_by_symbol, dict):
        raise ScopeProvenanceError("execution evidence requires symbol-keyed candle payloads")
    symbols = tuple(sorted(record.symbol for record in records))
    if len(set(symbols)) != len(symbols):
        raise ScopeProvenanceError("execution evidence requires one dataset per symbol")
    if set(symbols) != set(candles_by_symbol):
        raise ScopeProvenanceError("execution evidence symbols do not match candle payloads")

    records_by_symbol = {record.symbol: record for record in records}
    canonical_rows = []
    row_counts = []
    for symbol in symbols:
        record = records_by_symbol[symbol]
        payload = validate_candle_payload(candles_by_symbol[symbol], (record,))
        digest, count = hash_backtest_candles(payload)
        canonical_rows.append({
            "symbol": symbol,
            "dataset_hash": digest,
            "row_count": count,
        })
        row_counts.append(count)

    payload_hash = hashlib.sha256(
        json.dumps(canonical_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    provenance_fingerprint = hash_dataset_provenance(records)
    supplied = (strategy_fingerprint, configuration_fingerprint)
    if (supplied[0] is None) != (supplied[1] is None):
        raise ScopeProvenanceError(
            "strategy and configuration fingerprints must be supplied together"
        )
    if supplied[0] is not None and any(
        not isinstance(value, str) or not _HASH.fullmatch(value) for value in supplied
    ):
        raise ScopeProvenanceError("strategy/configuration fingerprints must be SHA-256")
    execution_fingerprint = None
    if supplied[0] is not None:
        execution_fingerprint = hashlib.sha256(
            json.dumps({
                "payload_hash": payload_hash,
                "provenance_fingerprint": provenance_fingerprint,
                "strategy_fingerprint": strategy_fingerprint,
                "configuration_fingerprint": configuration_fingerprint,
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    ordered_records = tuple(records_by_symbol[symbol] for symbol in symbols)
    return BacktestExecutionEvidence(
        dataset_provenance=ordered_records,
        symbols=symbols,
        row_counts=tuple(row_counts),
        payload_hash=payload_hash,
        provenance_fingerprint=provenance_fingerprint,
        strategy_fingerprint=strategy_fingerprint,
        configuration_fingerprint=configuration_fingerprint,
        execution_fingerprint=execution_fingerprint,
    )
