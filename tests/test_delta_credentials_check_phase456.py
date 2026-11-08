from core.exchanges.delta.delta_exchange import DeltaExchange
from scripts.check_delta_credentials import verify_credentials


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class IdentityREST:
    authenticated = True

    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.client = FakeSession()

    def get(self, path, params=None):
        self.calls.append((path, params))
        if self.failure is not None:
            raise self.failure
        return {"success": True, "result": {"user_id": 918273}}


def test_personal_credential_check_uses_identity_endpoint_only():
    rest = IdentityREST()
    exchange = DeltaExchange(
        api_key="synthetic-personal-key",
        api_secret="synthetic-personal-secret",
        rest=rest,
    )
    output = []
    result = verify_credentials(client_factory=lambda: exchange, emit=output.append)
    assert result == 0
    assert rest.calls == [("/v2/users/trading_preferences", None)]
    assert rest.client.closed
    rendered = "\n".join(output)
    assert "PASS" in rendered
    assert "synthetic-personal-key" not in rendered
    assert "synthetic-personal-secret" not in rendered
    assert "918273" not in rendered


def test_personal_credential_check_redacts_transport_failure():
    rest = IdentityREST(failure=RuntimeError("api_secret=must-not-leak"))
    exchange = DeltaExchange(
        api_key="synthetic-personal-key",
        api_secret="synthetic-personal-secret",
        rest=rest,
    )
    output = []
    result = verify_credentials(client_factory=lambda: exchange, emit=output.append)
    assert result == 1
    rendered = "\n".join(output)
    assert "RuntimeError" in rendered
    assert "must-not-leak" not in rendered
    assert "synthetic-personal-secret" not in rendered
    assert rest.client.closed
