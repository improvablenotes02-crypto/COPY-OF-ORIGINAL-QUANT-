# Phase 483 - Flattrade option-chain contract normalization

The new normalizer converts Flattrade `GetOptionChain.values` rows into canonical `Instrument` records. It maps CE/PE rights, strike, exchange, token, tick size, lot size and price precision.

The vendor chain response does not supply an independently verified expiry field in the documented row schema. Therefore the caller must provide a positive `expiry_time`; the normalizer never guesses expiry from a trading symbol. It also rejects duplicate tokens/symbols, exchange mismatches, invalid lot sizes, invalid precision and unknown option rights.

Every normalized option is deliberately `trading_enabled=False`. `contract_multiplier_verified` is false in metadata; the neutral default multiplier is not certified for sizing or P&L. This conversion does not connect the contracts to a strategy, paper execution or live order path.
