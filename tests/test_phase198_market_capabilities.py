from __future__ import annotations

import pytest

from core.exchanges.market_capabilities import (
    InstrumentType,
    MarketCapabilities,
    MarketFamily,
)


def test_capabilities_default_to_no_live_execution():
    item = MarketCapabilities(
        adapter_name="example-research-adapter",
        venue="example",
        market_families=frozenset({MarketFamily.CRYPTO}),
        instrument_types=frozenset({InstrumentType.SPOT}),
        market_data=True,
        historical_data=True,
        paper_execution=True,
    )
    assert item.supports(MarketFamily.CRYPTO, InstrumentType.SPOT)
    assert not item.supports(MarketFamily.FOREX, InstrumentType.FX_SPOT)
    assert not item.live_execution_eligible


def test_live_order_flag_without_verified_evidence_is_not_eligible():
    item = MarketCapabilities(
        adapter_name="adapter",
        venue="venue",
        market_families=frozenset({MarketFamily.NSE_INDEX}),
        instrument_types=frozenset({InstrumentType.OPTION}),
        live_orders=True,
    )
    assert not item.live_execution_eligible


def test_verified_live_execution_requires_evidence_reference():
    with pytest.raises(ValueError, match="evidence reference"):
        MarketCapabilities(
            adapter_name="adapter",
            venue="venue",
            market_families=frozenset({MarketFamily.FOREX}),
            instrument_types=frozenset({InstrumentType.FX_SPOT}),
            live_orders=True,
            live_execution_verified=True,
        )


def test_live_eligibility_requires_all_three_conditions():
    item = MarketCapabilities(
        adapter_name="adapter",
        venue="venue",
        market_families=frozenset({MarketFamily.NSE_EQUITY}),
        instrument_types=frozenset({InstrumentType.CASH_EQUITY}),
        live_orders=True,
        live_execution_verified=True,
        live_execution_evidence="audit://venue-schema-and-write-tests/123",
    )
    assert item.live_execution_eligible
