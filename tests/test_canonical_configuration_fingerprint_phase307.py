"""Phase 307: canonical JSON hashing for effective backtest configuration."""
import pytest

from core.research.acquisition.scope_provenance import (
    BacktestConfigurationIdentity,
    ScopeProvenanceError,
    hash_canonical_json,
)


def test_configuration_hash_is_independent_of_mapping_insertion_order():
    first = {"risk": {"max_loss": 250, "daily_limit": 1000}, "symbols": ["BTCUSD", "ETHUSD"]}
    second = {"symbols": ["BTCUSD", "ETHUSD"], "risk": {"daily_limit": 1000, "max_loss": 250}}
    assert hash_canonical_json(first) == hash_canonical_json(second)


def test_configuration_hash_preserves_list_order():
    first = {"symbols": ["BTCUSD", "ETHUSD"]}
    second = {"symbols": ["ETHUSD", "BTCUSD"]}
    assert hash_canonical_json(first) != hash_canonical_json(second)


def test_configuration_identity_factory_uses_canonical_hash():
    config = {"risk": {"max_loss": 250}, "timeframe": "1m"}
    identity = BacktestConfigurationIdentity.from_configuration(
        config, configuration_version="v2", parameter_schema_version="3"
    )
    assert identity.configuration_sha256 == hash_canonical_json(config)
    assert len(identity.fingerprint) == 64


@pytest.mark.parametrize("value", [
    {"threshold": float("nan")},
    {"threshold": float("inf")},
    {1: "non-string-key"},
    {"values": {1, 2, 3}},
])
def test_ambiguous_or_non_json_configuration_values_are_rejected(value):
    with pytest.raises(ScopeProvenanceError):
        hash_canonical_json(value)
