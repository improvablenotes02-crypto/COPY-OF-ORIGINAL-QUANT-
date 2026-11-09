"""Phase 476: read-only Delta connectivity probe regression tests."""
from scripts.check_delta_connection import check_connection


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeREST:
    def __init__(self):
        self.client = FakeSession()


class FakeDelta:
    def __init__(self, *, identity="synthetic-account-id", catalog=None, failure=None):
        self.rest = FakeREST()
        self.identity = identity
        self.catalog = catalog if catalog is not None else {
            "success": True, "result": [{"id": 1, "symbol": "BTCUSDT"}]
        }
        self.failure = failure
        self.calls = []

    def _get_authenticated_account_id(self):
        self.calls.append("identity")
        if self.failure:
            raise self.failure
        return self.identity

    def get_products(self):
        self.calls.append("products")
        if self.failure:
            raise self.failure
        return self.catalog


def test_connectivity_check_verifies_identity_and_public_catalog_without_writes():
    client = FakeDelta()
    output = []
    result = check_connection(client_factory=lambda: client, emit=output.append)
    rendered = "\n".join(output)
    assert result == 0
    assert client.calls == ["identity", "products"]
    assert client.rest.client.closed
    assert "PASS" in rendered
    assert "1 products" in rendered
    assert "synthetic-account-id" not in rendered
    assert "Exchange writes: NOT USED" in rendered


def test_connectivity_check_redacts_authentication_exception_and_closes_session():
    client = FakeDelta(failure=RuntimeError("api_secret=do-not-print"))
    output = []
    result = check_connection(client_factory=lambda: client, emit=output.append)
    rendered = "\n".join(output)
    assert result == 1
    assert client.calls == ["identity"]
    assert client.rest.client.closed
    assert "RuntimeError" in rendered
    assert "do-not-print" not in rendered


def test_connectivity_check_rejects_unsuccessful_or_empty_catalog():
    for catalog in ({"success": False, "result": []}, {"success": True, "result": []}):
        client = FakeDelta(catalog=catalog)
        output = []
        assert check_connection(client_factory=lambda client=client: client, emit=output.append) == 1
        assert client.rest.client.closed
        assert "FAIL" in "\n".join(output)


def test_connectivity_check_rejects_malformed_catalog_rows():
    client = FakeDelta(catalog={"success": True, "result": ["not-a-product"]})
    output = []
    assert check_connection(client_factory=lambda: client, emit=output.append) == 1
    assert client.rest.client.closed
