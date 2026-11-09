"""Phase 481: Flattrade connection check is read-only and redacted."""
from scripts.check_flattrade_connection import check_flattrade_connection


class FakeClient:
    def __init__(self, details=None, failure=None):
        self.details = details if details is not None else {
            "stat": "Ok", "actid": "SENSITIVE-ACCOUNT-ID", "exarr": ["NSE", "NFO"]
        }
        self.failure = failure
        self.closed = False
        self.calls = 0

    def user_details(self):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.details

    def close(self):
        self.closed = True


def test_connection_check_uses_only_user_details_and_redacts_account_id():
    client = FakeClient()
    output = []
    result = check_flattrade_connection(
        credential_loader=lambda: ("USER123", "SENSITIVE-TOKEN"),
        client_factory=lambda uid, token: client,
        emit=output.append,
    )
    rendered = "\n".join(output)
    assert result == 0
    assert client.calls == 1 and client.closed
    assert "PASS" in rendered
    assert "2" in rendered
    assert "SENSITIVE-ACCOUNT-ID" not in rendered
    assert "SENSITIVE-TOKEN" not in rendered
    assert "Exchange writes: NOT USED" in rendered


def test_connection_check_stops_if_credentials_are_missing():
    calls = []
    output = []
    result = check_flattrade_connection(
        credential_loader=lambda: ("", ""),
        client_factory=lambda *args: calls.append(args),
        emit=output.append,
    )
    assert result == 1
    assert calls == []
    assert "FAIL" in "\n".join(output)


def test_connection_check_redacts_provider_failure_and_closes_client():
    client = FakeClient(failure=RuntimeError("jKey=SENSITIVE-TOKEN"))
    output = []
    result = check_flattrade_connection(
        credential_loader=lambda: ("USER123", "SENSITIVE-TOKEN"),
        client_factory=lambda *args: client,
        emit=output.append,
    )
    rendered = "\n".join(output)
    assert result == 1
    assert client.closed
    assert "RuntimeError" in rendered
    assert "SENSITIVE-TOKEN" not in rendered
