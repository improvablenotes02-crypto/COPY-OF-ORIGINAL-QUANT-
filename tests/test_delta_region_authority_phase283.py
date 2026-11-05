"""Phase 283: Delta Global/India region and environment isolation."""
from unittest import mock

import pytest

from core.exchanges.delta import delta_environments as env


@pytest.mark.parametrize(
    "environment,region,expected",
    [
        ("PRODUCTION", "GLOBAL", "https://api.delta.exchange"),
        ("SANDBOX", "GLOBAL", "https://testnet-api.delta.exchange"),
        ("PRODUCTION", "INDIA", "https://api.india.delta.exchange"),
        ("SANDBOX", "INDIA", "https://cdn-ind.testnet.deltaex.org"),
    ],
)
def test_rest_hosts_are_exactly_region_and_environment_scoped(environment, region, expected):
    assert env.resolve_rest_endpoint(environment, region) == expected
    assert env.assert_endpoint_for_environment(environment, expected, region) == expected


def test_india_websocket_hosts_match_official_region_environment_matrix():
    assert env.resolve_ws_endpoint("PRODUCTION", "INDIA") == "wss://public-socket.india.delta.exchange"
    assert env.resolve_private_ws_endpoint("PRODUCTION", "INDIA") == "wss://socket.india.delta.exchange"
    assert env.resolve_ws_endpoint("SANDBOX", "INDIA") == "wss://socket-ind-pub.testnet.deltaex.org"
    assert env.resolve_private_ws_endpoint("SANDBOX", "INDIA") == "wss://socket-ind.testnet.deltaex.org"


def test_global_sandbox_websocket_remains_unverified_and_fails_closed():
    with pytest.raises(env.EnvironmentError, match="unverified"):
        env.resolve_ws_endpoint("SANDBOX", "GLOBAL")
    with pytest.raises(env.EnvironmentError, match="unverified"):
        env.resolve_private_ws_endpoint("SANDBOX", "GLOBAL")


@pytest.mark.parametrize(
    "environment,region,wrong_host",
    [
        ("PRODUCTION", "INDIA", "https://api.delta.exchange"),
        ("SANDBOX", "INDIA", "https://testnet-api.delta.exchange"),
        ("PRODUCTION", "GLOBAL", "https://api.india.delta.exchange"),
        ("SANDBOX", "GLOBAL", "https://cdn-ind.testnet.deltaex.org"),
    ],
)
def test_cross_region_endpoint_pairings_are_rejected(environment, region, wrong_host):
    with pytest.raises(env.EnvironmentError):
        env.assert_endpoint_for_environment(environment, wrong_host, region)


def test_unknown_region_never_falls_back_to_global():
    assert env.resolve_region("earth") == env.UNKNOWN_REGION
    with pytest.raises(env.EnvironmentError):
        env.resolve_rest_endpoint("PRODUCTION", "earth")
    with pytest.raises(env.EnvironmentError):
        env.credentials_for("PRODUCTION", "earth")


def test_credentials_are_isolated_across_four_venue_scopes():
    from config import settings as settings_mod
    patches = [
        mock.patch.object(settings_mod.settings, "API_KEY", "global-prod-key"),
        mock.patch.object(settings_mod.settings, "API_SECRET", "global-prod-secret"),
        mock.patch.object(settings_mod.settings, "SANDBOX_API_KEY", "global-demo-key"),
        mock.patch.object(settings_mod.settings, "SANDBOX_API_SECRET", "global-demo-secret"),
        mock.patch.object(settings_mod.settings, "INDIA_API_KEY", "india-prod-key"),
        mock.patch.object(settings_mod.settings, "INDIA_API_SECRET", "india-prod-secret"),
        mock.patch.object(settings_mod.settings, "INDIA_SANDBOX_API_KEY", "india-demo-key"),
        mock.patch.object(settings_mod.settings, "INDIA_SANDBOX_API_SECRET", "india-demo-secret"),
    ]
    with mock.ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        assert env.credentials_for("PRODUCTION", "GLOBAL") == ("global-prod-key", "global-prod-secret")
        assert env.credentials_for("SANDBOX", "GLOBAL") == ("global-demo-key", "global-demo-secret")
        assert env.credentials_for("PRODUCTION", "INDIA") == ("india-prod-key", "india-prod-secret")
        assert env.credentials_for("SANDBOX", "INDIA") == ("india-demo-key", "india-demo-secret")


def test_india_demo_never_substitutes_global_demo_or_production_keys():
    from config import settings as settings_mod
    with mock.patch.object(settings_mod.settings, "API_KEY", "global-prod"), \
         mock.patch.object(settings_mod.settings, "API_SECRET", "global-prod-secret"), \
         mock.patch.object(settings_mod.settings, "SANDBOX_API_KEY", "global-demo"), \
         mock.patch.object(settings_mod.settings, "SANDBOX_API_SECRET", "global-demo-secret"), \
         mock.patch.object(settings_mod.settings, "INDIA_API_KEY", ""), \
         mock.patch.object(settings_mod.settings, "INDIA_API_SECRET", ""), \
         mock.patch.object(settings_mod.settings, "INDIA_SANDBOX_API_KEY", ""), \
         mock.patch.object(settings_mod.settings, "INDIA_SANDBOX_API_SECRET", ""):
        with pytest.raises(env.EnvironmentError, match="INDIA SANDBOX credentials"):
            env.credentials_for("SANDBOX", "INDIA")


def test_india_client_factory_pins_host_and_region_specific_credentials():
    from config import settings as settings_mod
    with mock.patch.object(settings_mod.settings, "INDIA_SANDBOX_API_KEY", "india-demo"), \
         mock.patch.object(settings_mod.settings, "INDIA_SANDBOX_API_SECRET", "india-demo-secret"):
        client = env.india_sandbox_client()
    assert client.api_key == "india-demo"
    assert client.api_secret == "india-demo-secret"
    assert client.rest.base_url == "https://cdn-ind.testnet.deltaex.org"
