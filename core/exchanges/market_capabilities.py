"""Declarative, fail-closed capability metadata for multi-market adapters.

This module is groundwork only: it does not connect to venues or authorize
orders. Live execution is eligible only when a concrete adapter advertises
support AND records venue-specific verification evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


class MarketFamily(str, Enum):
    CRYPTO = "crypto"
    NSE_EQUITY = "nse_equity"
    NSE_INDEX = "nse_index"
    FOREX = "forex"


class InstrumentType(str, Enum):
    SPOT = "spot"
    PERPETUAL = "perpetual"
    FUTURE = "future"
    OPTION = "option"
    CASH_EQUITY = "cash_equity"
    FX_SPOT = "fx_spot"


@dataclass(frozen=True, slots=True)
class MarketCapabilities:
    """Declared adapter abilities; defaults deliberately deny live execution."""

    adapter_name: str
    venue: str
    market_families: FrozenSet[MarketFamily]
    instrument_types: FrozenSet[InstrumentType]
    market_data: bool = False
    historical_data: bool = False
    paper_execution: bool = False
    live_orders: bool = False
    live_execution_verified: bool = False
    live_execution_evidence: str = ""

    def __post_init__(self) -> None:
        if not self.adapter_name.strip() or not self.venue.strip():
            raise ValueError("adapter_name and venue are required")
        if not self.market_families:
            raise ValueError("at least one market family must be declared")
        if self.live_execution_verified and not self.live_execution_evidence.strip():
            raise ValueError("verified live execution requires evidence reference")

    @property
    def live_execution_eligible(self) -> bool:
        """A declaration is not enough: all write-safety conditions must hold."""
        return bool(
            self.live_orders
            and self.live_execution_verified
            and self.live_execution_evidence.strip()
        )

    def supports(self, family: MarketFamily, instrument: InstrumentType) -> bool:
        return family in self.market_families and instrument in self.instrument_types
