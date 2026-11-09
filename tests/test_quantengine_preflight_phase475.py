"""Phase 475: offline operator preflight is exact, redacted and fail-closed."""
from types import SimpleNamespace

import pytest

from scripts.quantengine_preflight import inspect_configuration


@pytest.mark.parametrize(
    "region,environment",
    [
        ("GLOBAL", "PRODUCTION"),
        ("GLOBAL", "SANDBOX"),
        ("INDIA", "PRODUCTION"),
        ("INDIA", "SANDBOX"),
    ],
)
def test_preflight_accepts_only_the_selected_region_environment_pair(region, environment):
    config = SimpleNamespace(
        DELTA_REGION=region, DELTA_ENVIRONMENT=environment,
        PAPER_MODE=True, ALLOW_LIVE=False, LIVE_EXECUTE=False, LIVE_MODE=False,
    )
    calls = []
    def resolver(env, reg):
        calls.append((env, reg))
        return "synthetic-key", "synthetic-secret"

    report = inspect_configuration(config=config, credential_resolver=resolver)
    assert report["ready_for_authenticated_read_only_check"] is True
    assert report["credentials"] == "CONFIGURED"
    assert report["live_flags_disarmed"] is True
    assert calls == [(environment, region)]
    assert "synthetic-key" not in repr(report)
    assert "synthetic-secret" not in repr(report)


@pytest.mark.parametrize("field,value", [
    ("ALLOW_LIVE", True),
    ("LIVE_EXECUTE", True),
    ("LIVE_MODE", True),
])
def test_preflight_fails_closed_if_any_live_flag_is_present(field, value):
    config = SimpleNamespace(
        DELTA_REGION="INDIA", DELTA_ENVIRONMENT="SANDBOX",
        PAPER_MODE=True, ALLOW_LIVE=False, LIVE_EXECUTE=False, LIVE_MODE=False,
    )
    setattr(config, field, value)
    report = inspect_configuration(
        config=config,
        credential_resolver=lambda env, reg: ("synthetic-key", "synthetic-secret"),
    )
    assert report["ready_for_authenticated_read_only_check"] is False
    assert report["live_flags_disarmed"] is False
    assert any("Live execution flags" in error for error in report["errors"])


def test_preflight_reports_missing_credentials_without_fallback():
    config = SimpleNamespace(
        DELTA_REGION="INDIA", DELTA_ENVIRONMENT="PRODUCTION",
        PAPER_MODE=True, ALLOW_LIVE=False, LIVE_EXECUTE=False, LIVE_MODE=False,
    )
    def missing(env, reg):
        raise ValueError("credential details must not leak")
    report = inspect_configuration(config=config, credential_resolver=missing)
    assert report["ready_for_authenticated_read_only_check"] is False
    assert report["credentials"] == "UNAVAILABLE"
    assert "credential details" not in repr(report)


def test_preflight_rejects_unknown_region_or_environment_before_credential_lookup():
    config = SimpleNamespace(
        DELTA_REGION="OTHER", DELTA_ENVIRONMENT="UNKNOWN",
        PAPER_MODE=True, ALLOW_LIVE=False, LIVE_EXECUTE=False, LIVE_MODE=False,
    )
    called = []
    report = inspect_configuration(config=config, credential_resolver=lambda *args: called.append(args))
    assert report["ready_for_authenticated_read_only_check"] is False
    assert called == []
    assert report["endpoint"] is None
