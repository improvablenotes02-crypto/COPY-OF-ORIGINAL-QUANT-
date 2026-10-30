from core.exchanges.adapter_conformance import probe_read_only_behavior


class GoodAdapter:
    def __init__(self):
        self.calls = []

    def get_products(self):
        self.calls.append("products")
        return [{"symbol": "TEST"}]

    def get_balance(self):
        self.calls.append("balance")
        return {"available": "100.00"}

    def get_positions(self):
        self.calls.append("positions")
        return []

    def place_order(self, order):
        raise AssertionError("probe must never call order methods")


def test_probe_checks_read_shapes_and_never_calls_order_methods():
    adapter = GoodAdapter()
    report = probe_read_only_behavior(adapter, "simulated")
    assert report.passed
    assert report.products_count == 1
    assert report.balance_type == "dict"
    assert report.positions_count == 0
    assert adapter.calls == ["products", "balance", "positions"]


def test_probe_rejects_wrong_return_shapes():
    class BadShapes:
        def get_products(self): return {"not": "a list"}
        def get_balance(self): return []
        def get_positions(self): return None

    report = probe_read_only_behavior(BadShapes(), "bad-shapes")
    assert not report.passed
    assert "get_products must return list or tuple" in report.errors
    assert "get_balance must return a mapping" in report.errors
    assert "get_positions must return list or tuple" in report.errors


def test_probe_sanitizes_exceptions_and_continues():
    class Unstable:
        def get_products(self): raise RuntimeError("secret token must not leak")
        def get_balance(self): return {"available": 0}
        def get_positions(self): return []

    report = probe_read_only_behavior(Unstable(), "unstable")
    assert not report.passed
    assert "get_products raised RuntimeError" in report.errors
    assert all("secret token" not in error for error in report.errors)
    assert report.balance_type == "dict"
    assert report.positions_count == 0


def test_probe_missing_method_is_fail_closed():
    class Incomplete:
        def get_products(self): return []
        def get_balance(self): return {}

    report = probe_read_only_behavior(Incomplete())
    assert not report.passed
    assert "missing callable read method: get_positions" in report.errors
