"""Phase 295: verify immutable execution evidence envelope consistency."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backtesting.backtester import Backtester
from core.research.acquisition.scope_provenance import (
    DatasetScopeProvenance,
    ScopeProvenanceError,
    hash_backtest_candles,
)


def _outcome():
    candles = [
        SimpleNamespace(timestamp=1, open=10.0, high=12.0, low=9.0,
                        close=11.0, volume=100.0, closed=True, symbol="BTCUSD"),
        SimpleNamespace(timestamp=2, open=11.0, high=13.0, low=10.0,
                        close=12.0, volume=120.0, closed=True, symbol="BTCUSD"),
    ]
    digest, count = hash_backtest_candles(candles)
    scope = DatasetScopeProvenance(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash=digest, row_count=count,
        completeness="COMPLETE", pagination_exhausted=True,
    )

    class Harness(Backtester):
        def __init__(self):
            pass

        def run(self, bars, journal=None):
            return {"count": len(bars)}

    return Harness().run_scoped_with_evidence(
        candles, [scope], strategy_fingerprint="a" * 64,
        configuration_fingerprint="b" * 64,
        engine_fingerprint="d" * 64,
    )


def test_valid_evidence_verifies_and_is_immutable():
    evidence = _outcome().evidence
    assert evidence.verify() is True
    assert isinstance(evidence.dataset_provenance, tuple)
    assert isinstance(evidence.symbols, tuple)
    assert isinstance(evidence.row_counts, tuple)


@pytest.mark.parametrize("changes,match", [
    ({"payload_hash": "f" * 64}, "payload hash"),
    ({"row_counts": (999,)}, "row-count"),
    ({"symbols": ("ETHUSD",)}, "symbol/provenance"),
    ({"execution_fingerprint": "e" * 64}, "execution fingerprint"),
])
def test_tampered_evidence_envelope_rejected_at_construction(changes, match):
    evidence = _outcome().evidence
    with pytest.raises(ScopeProvenanceError, match=match):
        replace(evidence, **changes)


def test_evidence_rejects_symbol_dimension_mismatch():
    evidence = _outcome().evidence
    with pytest.raises(ScopeProvenanceError, match="symbol/provenance"):
        replace(evidence, symbols=("ETHUSD",))
