"""Phase 457: credential diagnostics expose only fixed failure categories."""

import pytest

from core.exchanges.delta.delta_exchange import DeltaExchange
from scripts.check_delta_credentials import verify_credentials


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeHTTPError(Exception):
    def __init__(self, status_code, payload):
        self.response = FakeResponse(status_code, payload)


class IdentityREST:
    authenticated = True

    def __init__(self, failure):
        self.calls = []
        self.failure = failure
        self.client = FakeSession()

    def get(self, path, params=None):
        self.calls.append((path, params))
        raise self.failure


def _run_failure(failure):
    rest = IdentityREST(failure)
    exchange = DeltaExchange(
        api_key="synthetic-personal-key",
        api_secret="synthetic-personal-secret",
        rest=rest,
    )
    output = []
    result = verify_credentials(
        client_factory=lambda: exchange,
        emit=output.append,
    )
    return result, "\n".join(output), rest


@pytest.mark.parametrize(
    ("code", "expected_category"),
    [
        ("invalid_api_key", "INVALID_API_KEY"),
        ("signature_mismatch", "INVALID_SIGNATURE"),
        ("signature_expired", "TIMESTAMP_ERROR"),
        ("ip_not_whitelisted_for_api_key", "IP_NOT_WHITELISTED"),
        ("unauthorized_api_access", "PERMISSION_DENIED"),
    ],
)
def test_known_provider_failures_map_to_fixed_redacted_categories(
    code, expected_category
):
    failure = FakeHTTPError(
        403,
        {
            "success": False,
            "error": {
                "code": code,
                "message": "provider detail must not be emitted",
                "context": {"api_secret": "must-not-leak"},
            },
        },
    )
    result, rendered, rest = _run_failure(failure)

    assert result == 1
    assert expected_category in rendered
    assert code not in rendered
    assert "provider detail must not be emitted" not in rendered
    assert "must-not-leak" not in rendered
    assert "synthetic-personal-secret" not in rendered
    assert rest.calls == [("/v2/users/trading_preferences", None)]
    assert rest.client.closed


def test_malformed_error_body_uses_http_status_without_echoing_body():
    failure = FakeHTTPError(
        403,
        ValueError("api_secret=malformed-body-must-not-leak"),
    )
    result, rendered, rest = _run_failure(failure)

    assert result == 1
    assert "PERMISSION_DENIED" in rendered
    assert "malformed-body-must-not-leak" not in rendered
    assert rest.client.closed


def test_unknown_provider_code_is_generic_and_never_echoed():
    private_code = "api_secret=unknown-code-must-not-leak"
    failure = FakeHTTPError(
        401,
        {"success": False, "error": {"code": private_code}},
    )
    result, rendered, rest = _run_failure(failure)

    assert result == 1
    assert "AUTHENTICATION_FAILED" in rendered
    assert private_code not in rendered
    assert rest.client.closed


def test_transport_exception_without_http_response_is_generic():
    result, rendered, rest = _run_failure(
        RuntimeError("api_secret=transport-detail-must-not-leak")
    )

    assert result == 1
    assert "AUTHENTICATION_FAILED" in rendered
    assert "transport-detail-must-not-leak" not in rendered
    assert rest.client.closed
