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
        if item.data_class == "PRIVATE_ACCOUNT" and item.account != first.account:
            raise ScopeProvenanceError("private account identity mismatch")
    return items
