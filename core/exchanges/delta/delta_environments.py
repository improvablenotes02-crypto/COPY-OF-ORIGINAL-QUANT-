"""
Delta environment and region authority.

Global and India are separate venues with different REST/WebSocket hosts
and environment-bound credentials. Callers must select both environment
(PRODUCTION/SANDBOX) and region (GLOBAL/INDIA) through this module.

Legacy no-region calls intentionally remain GLOBAL for compatibility.
New deployments should set DELTA_REGION explicitly. No credential or
endpoint is ever inferred from another region or environment.
"""
from __future__ import annotations

PRODUCTION = "PRODUCTION"
SANDBOX = "SANDBOX"
UNKNOWN = "UNKNOWN"
GLOBAL = "GLOBAL"
INDIA = "INDIA"
UNKNOWN_REGION = "UNKNOWN"

ENVIRONMENTS = (PRODUCTION, SANDBOX)
REGIONS = (GLOBAL, INDIA)

_ENDPOINTS = {
    (GLOBAL, PRODUCTION): {
        "rest": "https://api.delta.exchange",
        "public_ws": "wss://public-socket.delta.exchange",
        "private_ws": "wss://socket.delta.exchange",
    },
    (GLOBAL, SANDBOX): {
        "rest": "https://testnet-api.delta.exchange",
        "public_ws": None,
        "private_ws": None,
    },
    (INDIA, PRODUCTION): {
        "rest": "https://api.india.delta.exchange",
        "public_ws": "wss://public-socket.india.delta.exchange",
        "private_ws": "wss://socket.india.delta.exchange",
    },
    (INDIA, SANDBOX): {
        "rest": "https://cdn-ind.testnet.deltaex.org",
        "public_ws": "wss://socket-ind-pub.testnet.deltaex.org",
        "private_ws": "wss://socket-ind.testnet.deltaex.org",
    },
}

# Compatibility constants retained for existing Global callers.
PRODUCTION_REST_URL = _ENDPOINTS[(GLOBAL, PRODUCTION)]["rest"]
SANDBOX_REST_URL = _ENDPOINTS[(GLOBAL, SANDBOX)]["rest"]
PRODUCTION_WS_URL = _ENDPOINTS[(GLOBAL, PRODUCTION)]["public_ws"]
SANDBOX_WS_URL: str | None = None

class EnvironmentError(ValueError):
    """An environment/region/endpoint/credential combination is unsafe."""

def approved_rest_endpoints() -> tuple[str, ...]:
    """Exact REST origins approved for supported region/environment pairs."""
    return tuple(sorted({
        entry["rest"] for entry in _ENDPOINTS.values()
        if isinstance(entry.get("rest"), str) and entry["rest"]
    }))


def resolve_environment(name: object) -> str:
    if isinstance(name, str) and name.strip().upper() in ENVIRONMENTS:
        return name.strip().upper()
    return UNKNOWN

def resolve_region(name: object = GLOBAL) -> str:
    if isinstance(name, str) and name.strip().upper() in REGIONS:
        return name.strip().upper()
    return UNKNOWN_REGION

def _endpoint(environment: object, region: object, kind: str) -> str:
    env = resolve_environment(environment)
    reg = resolve_region(region)
    if env == UNKNOWN or reg == UNKNOWN_REGION:
        raise EnvironmentError("UNKNOWN Delta environment or region refuses endpoint resolution")
    value = _ENDPOINTS[(reg, env)][kind]
    if not isinstance(value, str) or not value:
        raise EnvironmentError(
            f"{reg} {env} {kind} endpoint is unverified; refusing fallback")
    return value

def resolve_rest_endpoint(environment: object, region: object = GLOBAL) -> str:
    return _endpoint(environment, region, "rest")

def resolve_ws_endpoint(environment: object, region: object = GLOBAL) -> str:
    """Resolve the public market-data WebSocket endpoint."""
    return _endpoint(environment, region, "public_ws")

def resolve_private_ws_endpoint(environment: object, region: object = GLOBAL) -> str:
    """Resolve the authenticated private WebSocket endpoint."""
    return _endpoint(environment, region, "private_ws")

def _canonical_url(url: object) -> str:
    if not isinstance(url, str) or not url.strip():
        raise EnvironmentError("endpoint is missing or malformed")
    value = url.strip().rstrip("/")
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "wss") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise EnvironmentError("endpoint must be an exact HTTPS/WSS origin")
    return value

def assert_endpoint_for_environment(
    environment: object, url: object, region: object = GLOBAL
) -> str:
    env = resolve_environment(environment)
    reg = resolve_region(region)
    if env == UNKNOWN or reg == UNKNOWN_REGION:
        raise EnvironmentError("UNKNOWN Delta environment or region cannot authorize an endpoint")
    canonical = _canonical_url(url)
    expected = resolve_rest_endpoint(env, reg)
    if canonical != expected:
        raise EnvironmentError(
            f"{reg} {env} refuses endpoint {canonical!r}; expected {expected!r}")
    return canonical

def credentials_for(environment: object, region: object | None = None) -> tuple[str, str]:
    """Return only credentials explicitly provisioned for this venue and region."""
    from config.settings import settings
    env = resolve_environment(environment)
    reg = resolve_region(settings.DELTA_REGION if region is None else region)
    if env == UNKNOWN or reg == UNKNOWN_REGION:
        raise EnvironmentError("UNKNOWN Delta environment or region refuses credential resolution")
    names = {
        (GLOBAL, PRODUCTION): ("API_KEY", "API_SECRET"),
        (GLOBAL, SANDBOX): ("SANDBOX_API_KEY", "SANDBOX_API_SECRET"),
        (INDIA, PRODUCTION): ("INDIA_API_KEY", "INDIA_API_SECRET"),
        (INDIA, SANDBOX): ("INDIA_SANDBOX_API_KEY", "INDIA_SANDBOX_API_SECRET"),
    }[(reg, env)]
    key = str(getattr(settings, names[0], "") or "")
    secret = str(getattr(settings, names[1], "") or "")
    if not key or not secret:
        raise EnvironmentError(
            f"{reg} {env} credentials are unavailable; no cross-region or cross-environment fallback is permitted")
    return key, secret

def client_for(environment: object, region: object | None = None) -> object:
    """Construct a Delta client with region/environment-pinned credentials and REST host."""
    from config.settings import settings
    from core.exchanges.delta.delta_exchange import DeltaExchange
    env = resolve_environment(environment)
    reg = resolve_region(settings.DELTA_REGION if region is None else region)
    endpoint = assert_endpoint_for_environment(env, resolve_rest_endpoint(env, reg), reg)
    key, secret = credentials_for(env, reg)
    return DeltaExchange(api_key=key, api_secret=secret, base_url=endpoint)

def sandbox_client(region: object | None = None) -> object:
    """Backward-compatible explicit sandbox factory; region defaults to legacy GLOBAL."""
    return client_for(SANDBOX, region)

def configured_client() -> object:
    """Construct from explicit DELTA_ENVIRONMENT and DELTA_REGION settings."""
    from config.settings import settings
    return client_for(settings.DELTA_ENVIRONMENT, settings.DELTA_REGION)

def india_sandbox_client() -> object:
    return client_for(SANDBOX, INDIA)

def india_production_client() -> object:
    return client_for(PRODUCTION, INDIA)


def configured_public_rest() -> object:
    """Create a public REST transport for the selected Delta venue.

    Public endpoints do not need private credentials, but their host is
    region/environment-specific. Missing or invalid selection fails closed.
    """
    from config.settings import settings
    from core.exchanges.delta.delta_rest import DeltaREST

    endpoint = resolve_rest_endpoint(
        settings.DELTA_ENVIRONMENT, settings.DELTA_REGION
    )
    return DeltaREST(base_url=endpoint)
