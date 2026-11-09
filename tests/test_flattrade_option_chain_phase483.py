"""Phase 483: Flattrade option-chain contract normalization tests."""
import pytest

from core.registry.product_types import PRODUCT_CALL_OPTION, PRODUCT_PUT_OPTION
from data.flattrade.option_chain_normalization import (
    FlattradeOptionChainNormalizationError,
    normalize_option_chain,
)


def _contract(symbol, token, right, strike="22500", exchange="NFO"):
    return {
        "exch": exchange, "tsym": symbol, "token": token, "optt": right,
        "strprc": strike, "pp": "2", "ti": "0.05", "ls": "25",
    }


def test_normalizer_maps_call_and_put_contracts_and_keeps_them_non_tradable():
    contracts = normalize_option_chain(
        [
            _contract("NIFTY26NOV22500PE", "1002", "PE"),
            _contract("NIFTY26NOV22500CE", "1001", "CE"),
        ],
        underlying="NIFTY", exchange="NFO", expiry_time=1795671000,
    )
    assert len(contracts) == 2
    call, put = contracts
    assert call.symbol.endswith("CE") and put.symbol.endswith("PE")
    assert call.product_type == PRODUCT_CALL_OPTION
    assert put.product_type == PRODUCT_PUT_OPTION
    assert call.option_type == "call" and put.option_type == "put"
    assert call.underlying_asset == "NIFTY"
    assert call.expiry_time == 1795671000
    assert call.lot_size == 25
    assert call.tick_size == 0.05
    assert call.valid_option_contract_metadata
    assert all(item.trading_enabled is False for item in contracts)
    assert all(item.metadata["contract_multiplier_verified"] is False for item in contracts)


def test_normalizer_requires_caller_verified_expiry_instead_of_guessing_from_symbol():
    with pytest.raises(FlattradeOptionChainNormalizationError, match="verified expiry_time"):
        normalize_option_chain(
            [_contract("NIFTY26NOV22500CE", "1001", "CE")],
            underlying="NIFTY", exchange="NFO", expiry_time=0,
        )


def test_normalizer_rejects_duplicate_token_or_symbol_and_wrong_exchange():
    with pytest.raises(FlattradeOptionChainNormalizationError, match="duplicate"):
        normalize_option_chain(
            [
                _contract("NIFTY26NOV22500CE", "1001", "CE"),
                _contract("NIFTY26NOV22600CE", "1001", "CE", strike="22600"),
            ],
            underlying="NIFTY", exchange="NFO", expiry_time=1795671000,
        )
    with pytest.raises(FlattradeOptionChainNormalizationError, match="exchange mismatch"):
        normalize_option_chain(
            [_contract("NIFTY26NOV22500CE", "1001", "CE", exchange="BFO")],
            underlying="NIFTY", exchange="NFO", expiry_time=1795671000,
        )


@pytest.mark.parametrize(
    "row",
    [
        {**_contract("NIFTYCE", "1", "XX")},
        {**_contract("NIFTYCE", "1", "CE"), "strprc": "NaN"},
        {**_contract("NIFTYCE", "1", "CE"), "ti": "0"},
        {**_contract("NIFTYCE", "1", "CE"), "ls": "25.5"},
        {**_contract("NIFTYCE", "1", "CE"), "pp": "99"},
        {**_contract("NIFTYCE", "1", "CE"), "token": ""},
    ],
)
def test_normalizer_rejects_incomplete_or_invalid_contract_metadata(row):
    with pytest.raises(FlattradeOptionChainNormalizationError):
        normalize_option_chain(
            [row], underlying="NIFTY", exchange="NFO", expiry_time=1795671000
        )


def test_normalizer_rejects_empty_rows_and_sorts_by_strike_and_right():
    with pytest.raises(FlattradeOptionChainNormalizationError):
        normalize_option_chain([], underlying="NIFTY", exchange="NFO", expiry_time=1795671000)
    contracts = normalize_option_chain(
        [
            _contract("NIFTY22600PE", "4", "PE", strike="22600"),
            _contract("NIFTY22500PE", "3", "PE", strike="22500"),
            _contract("NIFTY22500CE", "2", "CE", strike="22500"),
        ],
        underlying="NIFTY", exchange="NFO", expiry_time=1795671000,
    )
    assert [item.strike_price for item in contracts] == [22500.0, 22500.0, 22600.0]
    assert [item.option_type for item in contracts] == ["call", "put", "put"]
