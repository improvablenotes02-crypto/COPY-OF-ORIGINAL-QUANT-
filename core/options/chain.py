"""Provider-neutral, fail-closed option-chain assembly."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Mapping, Sequence

from core.exchanges.market_data_validation import NormalizedQuote, validate_quote
from core.registry.instrument import Instrument
from core.registry.product_types import PRODUCT_CALL_OPTION, PRODUCT_PUT_OPTION


@dataclass(frozen=True, slots=True)
class OptionLeg:
    instrument: Instrument
    quote: NormalizedQuote | None


@dataclass(frozen=True, slots=True)
class OptionChainEntry:
    strike: float
    call: OptionLeg | None
    put: OptionLeg | None


@dataclass(frozen=True, slots=True)
class OptionChain:
    underlying: str
    expiry_time: int
    lot_size: int
    contract_multiplier: float
    as_of: datetime
    source: str
    entries: tuple[OptionChainEntry, ...]

    @property
    def missing_call_quotes(self) -> int:
        return sum(1 for entry in self.entries if entry.call is not None and entry.call.quote is None)

    @property
    def missing_put_quotes(self) -> int:
        return sum(1 for entry in self.entries if entry.put is not None and entry.put.quote is None)


def build_option_chain(
    instruments: Sequence[Instrument],
    quotes: Mapping[str, NormalizedQuote],
    *,
    underlying: str,
    expiry_time: int,
    as_of: datetime,
    max_quote_age_seconds: float = 5.0,
) -> OptionChain:
    """Pair calls/puts by strike; never synthesize missing legs or quotes."""
    if not isinstance(underlying, str) or not underlying.strip():
        raise ValueError("underlying is required")
    if isinstance(expiry_time, bool) or not isinstance(expiry_time, int) or expiry_time <= 0:
        raise ValueError("expiry_time must be a positive Unix timestamp")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    current = as_of.astimezone(timezone.utc)
    if expiry_time <= int(current.timestamp()):
        raise ValueError("option chain expiry is not in the future")
    try:
        max_age = float(max_quote_age_seconds)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("max_quote_age_seconds must be finite and non-negative") from None
    if not math.isfinite(max_age) or max_age < 0:
        raise ValueError("max_quote_age_seconds must be finite and non-negative")
    if not isinstance(instruments, Sequence) or isinstance(instruments, (str, bytes)) or not instruments:
        raise ValueError("option chain requires at least one instrument")
    if not isinstance(quotes, Mapping):
        raise TypeError("quotes must be a symbol-to-quote mapping")

    grouped: dict[float, dict[str, OptionLeg]] = {}
    seen_symbols: set[str] = set()
    sources: set[str] = set()
    common_lot: int | None = None
    common_multiplier: float | None = None

    for instrument in instruments:
        if not isinstance(instrument, Instrument):
            raise TypeError("option chain instruments must be canonical Instrument records")
        if instrument.symbol in seen_symbols:
            raise ValueError("duplicate option instrument symbol")
        seen_symbols.add(instrument.symbol)
        if instrument.product_type not in (PRODUCT_CALL_OPTION, PRODUCT_PUT_OPTION):
            raise ValueError("option chain contains a non-option instrument")
        if instrument.underlying_asset != underlying:
            raise ValueError("option chain underlying mismatch")
        if instrument.expiry_time != expiry_time:
            raise ValueError("option chain expiry mismatch")
        if not instrument.valid_option_contract_metadata:
            raise ValueError("option contract metadata is incomplete or inconsistent")
        if common_lot is None:
            common_lot = instrument.lot_size
            common_multiplier = float(instrument.contract_multiplier)
        elif instrument.lot_size != common_lot or float(instrument.contract_multiplier) != common_multiplier:
            raise ValueError("option chain lot size or multiplier mismatch")

        right = "call" if instrument.product_type == PRODUCT_CALL_OPTION else "put"
        strike = float(instrument.strike_price)
        legs = grouped.setdefault(strike, {})
        if right in legs:
            raise ValueError("duplicate %s contract at strike" % right)
        quote = quotes.get(instrument.symbol)
        if quote is not None:
            if not isinstance(quote, NormalizedQuote):
                raise TypeError("option quote values must be NormalizedQuote records")
            report = validate_quote(
                quote, now=current, max_age_seconds=max_age,
                expected_symbol=instrument.symbol,
            )
            if not report.valid:
                raise ValueError("invalid option quote: %s" % ", ".join(report.errors))
            sources.add(quote.source)
        legs[right] = OptionLeg(instrument=instrument, quote=quote)

    if len(sources) > 1:
        raise ValueError("option chain quotes must use one consistent source")
    entries = tuple(
        OptionChainEntry(strike=strike, call=legs.get("call"), put=legs.get("put"))
        for strike, legs in sorted(grouped.items())
    )
    return OptionChain(
        underlying=underlying,
        expiry_time=expiry_time,
        lot_size=common_lot,
        contract_multiplier=common_multiplier,
        as_of=current,
        source=next(iter(sources)) if sources else "",
        entries=entries,
    )
