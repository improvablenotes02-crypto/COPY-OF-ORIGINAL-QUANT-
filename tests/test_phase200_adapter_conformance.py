from core.exchanges.adapter_conformance import validate_adapter_conformance
from core.exchanges.market_capabilities import (
    InstrumentType, MarketCapabilities, MarketFamily,
)


def caps(**kwargs):
    defaults = dict(
        adapter_name="test-adapter",
        venue="test-venue",
        market_families=frozenset({MarketFamily.CRYPTO}),
        instrument_types=frozenset({InstrumentType.SPOT}),
    )
    defaults.update(kwargs)
    return MarketCapabilities(**defaults)


class ReadOnlyAdapter:
    def get_products(self): return []
    def get_balance(self): return {}
    def get_positions(self): return []


class FullAdapter(ReadOnlyAdapter):
    def place_order(self, order): raise NotImplementedError
    def cancel_order(self, order_id): raise NotImplementedError
    def get_order(self, order_id): raise NotImplementedError


def test_read_only_adapter_conforms_without_claiming_live_orders():
    report = validate_adapter_conformance(ReadOnlyAdapter(), caps())
    assert report.conforms
    assert report.live_execution_shape_valid


def test_missing_read_method_fails_closed():
    class Incomplete:
        def get_products(self): return []
        def get_balance(self): return {}
    report = validate_adapter_conformance(Incomplete(), caps())
    assert not report.conforms
    assert "missing callable read method: get_positions" in report.errors


def test_declared_live_orders_requires_all_order_methods():
    report = validate_adapter_conformance(
        ReadOnlyAdapter(), caps(live_orders=True))
    assert not report.conforms
    assert sum("live_orders declared" in error for error in report.errors) == 3


def test_full_shape_passes_but_does_not_grant_live_eligibility():
    capabilities = caps(live_orders=True)
    report = validate_adapter_conformance(FullAdapter(), capabilities)
    assert report.conforms
    assert not capabilities.live_execution_eligible


def test_evidence_and_method_shape_are_independent_gates():
    capabilities = caps(live_orders=True, live_execution_verified=True,
                         live_execution_evidence="audit://venue-test/123")
    assert capabilities.live_execution_eligible
    assert not validate_adapter_conformance(ReadOnlyAdapter(), capabilities).conforms
    assert validate_adapter_conformance(FullAdapter(), capabilities).conforms


def test_required_method_with_incompatible_signature_fails_closed():
    class BadSignature:
        def get_products(self, required_filter): return []
        def get_balance(self): return {}
        def get_positions(self): return []

    report = validate_adapter_conformance(BadSignature(), caps())
    assert not report.conforms
    assert "method signature incompatible with adapter contract: get_products" in report.errors


def test_live_order_method_must_accept_order_argument():
    class BadOrderShape(ReadOnlyAdapter):
        def place_order(self): return None
        def cancel_order(self, order_id): return None
        def get_order(self, order_id): return None

    report = validate_adapter_conformance(
        BadOrderShape(), caps(live_orders=True)
    )
    assert not report.conforms
    assert "method signature incompatible with adapter contract: place_order" in report.errors


def test_optional_adapter_parameters_are_allowed():
    class OptionalParams:
        def get_products(self, market=None): return []
        def get_balance(self, account=None): return {}
        def get_positions(self, account=None): return []

    assert validate_adapter_conformance(OptionalParams(), caps()).conforms
