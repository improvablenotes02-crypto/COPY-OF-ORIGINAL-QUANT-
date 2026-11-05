"""Phase 288: account and environment provenance isolation tests."""
import pytest

from core.research.acquisition.scope_provenance import (
    AccountDataIdentity,
    DatasetScopeProvenance,
    ScopeProvenanceError,
    validate_backtest_inputs,
)


def _dataset(**overrides):
    values = dict(
        venue="delta", region="INDIA", environment="SANDBOX",
        instrument="perpetual", symbol="BTCUSD", timeframe="1m",
        data_class="PUBLIC_MARKET", source="official-rest",
        source_timestamp="2026-11-05T10:00:00Z", schema_version="1",
        normalization_version="1", dataset_hash="a" * 64,
        row_count=100, completeness="COMPLETE", pagination_exhausted=True,
    )
    values.update(overrides)
    return DatasetScopeProvenance(**values)


def _account(tenant="tenant-a", internal="acct-1", provider="123"):
    return AccountDataIdentity(tenant, internal, provider)


def test_compatible_public_market_datasets_are_accepted():
    result = validate_backtest_inputs((_dataset(), _dataset(symbol="ETHUSD")))
    assert len(result) == 2


@pytest.mark.parametrize("override", [
    {"region": "GLOBAL"},
    {"environment": "PRODUCTION"},
    {"venue": "other-exchange"},
])
def test_backtest_rejects_cross_venue_region_or_environment(override):
    with pytest.raises(ScopeProvenanceError, match="mismatch"):
        validate_backtest_inputs((_dataset(), _dataset(**override)))


def test_backtest_rejects_demo_and_production_mixing():
    demo = _dataset(environment="SANDBOX")
    production = _dataset(environment="PRODUCTION")
    with pytest.raises(ScopeProvenanceError):
        validate_backtest_inputs((demo, production))


def test_private_account_data_requires_identity_and_exact_scope_match():
    with pytest.raises(ScopeProvenanceError, match="exact account identity"):
        _dataset(data_class="PRIVATE_ACCOUNT")
    first = _dataset(data_class="PRIVATE_ACCOUNT", account=_account())
    same = _dataset(data_class="PRIVATE_ACCOUNT", account=_account())
    other = _dataset(data_class="PRIVATE_ACCOUNT", account=_account(provider="999"))
    assert validate_backtest_inputs((first, same))
    with pytest.raises(ScopeProvenanceError, match="identity mismatch"):
        validate_backtest_inputs((first, other))


def test_public_and_private_data_cannot_be_mixed():
    public = _dataset()
    private = _dataset(data_class="PRIVATE_ACCOUNT", account=_account())
    with pytest.raises(ScopeProvenanceError, match="cannot be mixed"):
        validate_backtest_inputs((public, private))


def test_partial_or_unknown_dataset_is_not_backtest_eligible():
    with pytest.raises(ScopeProvenanceError, match="pagination evidence"):
        _dataset(completeness="COMPLETE", pagination_exhausted=False)
    partial = _dataset(completeness="PARTIAL", pagination_exhausted=False)
    with pytest.raises(ScopeProvenanceError, match="non-complete"):
        validate_backtest_inputs((partial,))
    unknown = _dataset(completeness="UNKNOWN", pagination_exhausted=False)
    with pytest.raises(ScopeProvenanceError, match="non-complete"):
        validate_backtest_inputs((unknown,))


@pytest.mark.parametrize("changes", [
    {"dataset_hash": "not-a-hash"},
    {"row_count": -1},
    {"row_count": True},
    {"region": "UNKNOWN"},
    {"environment": "PAPER"},
    {"data_class": "MIXED"},
])
def test_malformed_provenance_is_rejected(changes):
    with pytest.raises(ScopeProvenanceError):
        _dataset(**changes)


def test_private_identity_is_required_to_be_nonblank():
    with pytest.raises(ScopeProvenanceError, match="tenant_id"):
        _account(tenant=" ")
