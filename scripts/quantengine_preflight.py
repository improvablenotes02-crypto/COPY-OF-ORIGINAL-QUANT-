"""Offline operator preflight for the selected personal Delta account.

This command reads local configuration only. It does not contact Delta,
print credential values, inspect balances, or send exchange requests.
"""
from __future__ import annotations

import sys

from config.settings import settings
from core.exchanges.delta.delta_environments import (
    EnvironmentError,
    credentials_for,
    resolve_environment,
    resolve_region,
    resolve_rest_endpoint,
)


def inspect_configuration(*, config=settings, credential_resolver=credentials_for):
    """Return a redacted, deterministic readiness report without network I/O."""
    region = resolve_region(getattr(config, "DELTA_REGION", ""))
    environment = resolve_environment(getattr(config, "DELTA_ENVIRONMENT", ""))
    errors = []
    if region == "UNKNOWN":
        errors.append("DELTA_REGION must be INDIA or GLOBAL")
    if environment == "UNKNOWN":
        errors.append("DELTA_ENVIRONMENT must be PRODUCTION or SANDBOX")

    endpoint = None
    if not errors:
        try:
            endpoint = resolve_rest_endpoint(environment, region)
        except EnvironmentError:
            errors.append("Selected Delta endpoint is unavailable")

    credentials = "UNAVAILABLE"
    if not errors:
        try:
            key, secret = credential_resolver(environment, region)
            if isinstance(key, str) and key.strip() and isinstance(secret, str) and secret.strip():
                credentials = "CONFIGURED"
            else:
                errors.append("Selected Delta credential pair is incomplete")
        except EnvironmentError:
            errors.append("Selected Delta credential pair is unavailable")

    live_flags = any(
        bool(getattr(config, name, False))
        for name in ("ALLOW_LIVE", "LIVE_EXECUTE", "LIVE_MODE")
    )
    if live_flags:
        errors.append("Live execution flags are present; preflight requires them disarmed")

    return {
        "region": region,
        "environment": environment,
        "endpoint": endpoint,
        "credentials": credentials,
        "paper_mode": bool(getattr(config, "PAPER_MODE", False)),
        "live_flags_disarmed": not live_flags,
        "ready_for_authenticated_read_only_check": not errors and credentials == "CONFIGURED",
        "errors": tuple(errors),
    }


def main() -> int:
    report = inspect_configuration()
    print("QuantEngine offline operator preflight")
    print("Venue: {}/{}".format(report["region"], report["environment"]))
    print("REST endpoint: {}".format(report["endpoint"] or "UNAVAILABLE"))
    print("Selected credential pair: {}".format(report["credentials"]))
    print("Paper mode: {}".format("ON" if report["paper_mode"] else "OFF"))
    print("Live execution flags: {}".format(
        "DISARMED" if report["live_flags_disarmed"] else "PRESENT - STOP"
    ))
    for error in report["errors"]:
        print("ERROR: " + error)
    if report["ready_for_authenticated_read_only_check"]:
        print("Preflight: PASS (configuration only; no network request made)")
        print("Next: python scripts/check_delta_credentials.py")
        return 0
    print("Preflight: NOT READY")
    print("Configure the exact region/environment credential pair; never paste keys into logs.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
