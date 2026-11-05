"""Phase 290: portfolio-level dataset provenance admission tests."""
import pytest

from backtesting.portfolio_backtester import PortfolioBacktester
from core.research.acquisition.scope_provenance import (
    AccountDataIdentity,
    DatasetScopeProvenance,
    ScopeProvenanceError,
)


def _scope(symbol, **changes):
    values = dict(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol=symbol, timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash="c" * 64,
        row_count=10, completeness="COMPLETE", pagination_exhausted=True,
    )
    values.update(changes)
    return DatasetScopeProvenance(**values)


class _Engine:
    def __init__(self):
        self.calls = []

    def run(self, bars, journal=None):
        self.calls.append((bars, journal))
        return len(bars)


def _portfolio():
    portfolio = PortfolioBacktester(lambda symbol: (None, None))
    a, b = _Engine(), _Engine()
    portfolio.engines = {"BTCUSD": a, "ETHUSD": b}
    return portfolio, a, b


def test_portfolio_scoped_replay_validates_all_legs_then_runs():
    portfolio, a, b = _portfolio()
    history = {"BTCUSD": [1, 2], "ETHUSD": [3]}
    result = portfolio.run_scoped(
        history,
        {"BTCUSD": [_scope("BTCUSD")], "ETHUSD": [_scope("ETHUSD")]},
    )
    assert result == {"BTCUSD": 2, "ETHUSD": 1}
    assert len(a.calls) == len(b.calls) == 1


@pytest.mark.parametrize("bad", [
    _scope("ETHUSD", region="GLOBAL"),
    _scope("ETHUSD", environment="PRODUCTION"),
    _scope("ETHUSD", completeness="PARTIAL", pagination_exhausted=False),
])
def test_cross_leg_scope_mismatch_rejected_before_any_symbol_replay(bad):
    portfolio, a, b = _portfolio()
    with pytest.raises(ScopeProvenanceError):
        portfolio.run_scoped(
            {"BTCUSD": [1], "ETHUSD": [2]},
            {"BTCUSD": [_scope("BTCUSD")], "ETHUSD": [bad]},
        )
    assert a.calls == b.calls == []


def test_missing_or_extra_provenance_symbol_rejected_before_replay():
    portfolio, a, b = _portfolio()
    with pytest.raises(ScopeProvenanceError):
        portfolio.run_scoped(
            {"BTCUSD": [1], "ETHUSD": [2]},
            {"BTCUSD": [_scope("BTCUSD")]},
        )
    assert a.calls == b.calls == []


def test_symbol_key_must_match_dataset_identity():
    portfolio, a, b = _portfolio()
    with pytest.raises(ScopeProvenanceError):
        portfolio.run_scoped(
            {"BTCUSD": [1]},
            {"BTCUSD": [_scope("ETHUSD")]},
        )
    assert a.calls == []


def test_private_portfolio_requires_same_exact_account_across_symbols():
    portfolio, a, b = _portfolio()
    one = AccountDataIdentity("tenant", "internal-1", "provider-1")
    two = AccountDataIdentity("tenant", "internal-2", "provider-2")
    with pytest.raises(ScopeProvenanceError):
        portfolio.run_scoped(
            {"BTCUSD": [1], "ETHUSD": [2]},
            {
                "BTCUSD": [_scope("BTCUSD", data_class="PRIVATE_ACCOUNT", account=one)],
                "ETHUSD": [_scope("ETHUSD", data_class="PRIVATE_ACCOUNT", account=two)],
            },
        )
    assert a.calls == b.calls == []
