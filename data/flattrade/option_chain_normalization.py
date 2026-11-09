"""Normalize Flattrade option-chain contract rows into canonical Instruments.

Expiry is not inferred from the vendor chain rows: the caller must supply
an independently verified expiry timestamp. All returned contracts remain
non-tradable until a separate eligibility/evidence workflow approves them.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from core.registry.instrument import Instrument
from core.registry.product_types import PRODUCT_CALL_OPTION, PRODUCT_PUT_OPTION


class FlattradeOptionChainNormalizationError(ValueError):
    """A vendor option contract cannot be safely normalized."""


def _positive_decimal(row: dict, field: str, index: int) -> Decimal:
    try:
        value = Decimal(str(row[field]))
    except (KeyError, InvalidOperation, ValueError, TypeError):
        raise FlattradeOptionChainNormalizationError(
            "option row %d has invalid %s" % (index, field)
        ) from None
    if not value.is_finite() or value <= 0:
        raise FlattradeOptionChainNormalizationError(
            "option row %d has non-positive %s" % (index, field)
        )
    return value


def normalize_option_chain(
    rows, *, underlying: str, exchange: str, expiry_time: int,
    quote_asset: str = "INR",
) -> tuple[Instrument, ...]:
    """Convert GetOptionChain values into immutable canonical contract records."""
    if not isinstance(underlying, str) or not underlying.strip():
        raise FlattradeOptionChainNormalizationError("underlying is required")
    if not isinstance(exchange, str) or not exchange.strip():
        raise FlattradeOptionChainNormalizationError("exchange is required")
    if isinstance(expiry_time, bool) or not isinstance(expiry_time, int) or expiry_time <= 0:
        raise FlattradeOptionChainNormalizationError(
            "verified expiry_time must be a positive epoch timestamp"
        )
    if not isinstance(quote_asset, str) or not quote_asset.strip():
        raise FlattradeOptionChainNormalizationError("quote asset is required")
    if not isinstance(rows, (list, tuple)) or not rows:
        raise FlattradeOptionChainNormalizationError("option-chain rows are empty or malformed")

    canonical_underlying = underlying.strip().upper()
    canonical_exchange = exchange.strip().upper()
    canonical_quote = quote_asset.strip().upper()
    seen_tokens = set()
    seen_symbols = set()
    instruments = []

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise FlattradeOptionChainNormalizationError("option row %d is malformed" % index)
        row_exchange = row.get("exch")
        symbol = row.get("tsym")
        token = row.get("token")
        right = row.get("optt")
        if not isinstance(row_exchange, str) or row_exchange.strip().upper() != canonical_exchange:
            raise FlattradeOptionChainNormalizationError("option row %d exchange mismatch" % index)
        if not isinstance(symbol, str) or not symbol.strip():
            raise FlattradeOptionChainNormalizationError("option row %d symbol is missing" % index)
        if not isinstance(token, (str, int)) or isinstance(token, bool) or not str(token).strip():
            raise FlattradeOptionChainNormalizationError("option row %d token is missing" % index)
        token_text = str(token).strip()
        symbol_text = symbol.strip()
        if token_text in seen_tokens or symbol_text in seen_symbols:
            raise FlattradeOptionChainNormalizationError("duplicate option contract identity")
        seen_tokens.add(token_text)
        seen_symbols.add(symbol_text)

        if right not in ("CE", "PE"):
            raise FlattradeOptionChainNormalizationError("option row %d has unknown option right" % index)
        product_type = PRODUCT_CALL_OPTION if right == "CE" else PRODUCT_PUT_OPTION
        option_type = "call" if right == "CE" else "put"
        strike = _positive_decimal(row, "strprc", index)
        tick = _positive_decimal(row, "ti", index)
        lot_decimal = _positive_decimal(row, "ls", index)
        if lot_decimal != lot_decimal.to_integral_value():
            raise FlattradeOptionChainNormalizationError("option row %d lot size is not integral" % index)
        lot_size = int(lot_decimal)
        try:
            precision = int(row["pp"])
        except (KeyError, TypeError, ValueError):
            raise FlattradeOptionChainNormalizationError("option row %d price precision is missing" % index) from None
        if precision < 0 or precision > 12:
            raise FlattradeOptionChainNormalizationError("option row %d price precision is invalid" % index)

        instruments.append(Instrument(
            instrument_id="FLATTRADE:%s:%s" % (canonical_exchange, token_text),
            symbol=symbol_text,
            exchange=canonical_exchange,
            product_type=product_type,
            underlying_asset=canonical_underlying,
            quote_asset=canonical_quote,
            expiry_time=expiry_time,
            strike_price=float(strike),
            option_type=option_type,
            tick_size=float(tick),
            quantity_step=float(lot_size),
            minimum_quantity=float(lot_size),
            trading_enabled=False,
            metadata={
                "source": "FLATTRADE_GETOPTIONCHAIN",
                "token": token_text,
                "price_precision": precision,
                "contract_multiplier_verified": False,
                "raw_contract": dict(row),
            },
            lot_size=lot_size,
            contract_multiplier=1.0,
        ))

    instruments.sort(key=lambda item: (item.strike_price, item.option_type, item.symbol))
    return tuple(instruments)
