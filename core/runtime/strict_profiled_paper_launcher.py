"""Dedicated fail-closed launcher for the explicitly configured PAPER runtime.

Run with ``python -m core.runtime.strict_profiled_paper_launcher`` after setting
QE_PAPER_DATA_GATE_PROFILE=strict and QE_PAPER_DATA_MAX_AGE_SECONDS to a finite,
non-negative threshold. This launcher rejects compatibility mode before engine
construction and delegates only to the controlled PAPER lifecycle. It does not
modify or replace the frozen legacy ``main.py`` entrypoint.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Callable, Mapping, Sequence

from core.runtime.paper_gate_profile import (
    MAX_AGE_ENV, PROFILE_ENV, resolve_paper_gate_profile,
)
from core.runtime.profiled_paper_entrypoint import run_profiled_paper_with_monitoring


def run_strict_profiled_paper_launcher(
    *,
    builder: Callable | None = None,
    runner: Callable | None = None,
    environ: Mapping[str, str] | None = None,
    builder_kwargs: dict | None = None,
):
    """Run strict-profile PAPER only; reject missing/compat profile up front."""
    env = os.environ if environ is None else environ
    profile = str(env.get(PROFILE_ENV, "")).strip().lower()
    if profile != "strict":
        raise ValueError(
            f"{PROFILE_ENV}=strict is required by the strict PAPER launcher; "
            "compatibility fallback is disabled"
        )
    # Validate the required threshold here, before delegating or constructing
    # anything. The canonical profile resolver repeats full numeric validation.
    raw_age = env.get(MAX_AGE_ENV)
    if raw_age is None or not str(raw_age).strip():
        raise ValueError(f"{MAX_AGE_ENV} is required by the strict PAPER launcher")

    return run_profiled_paper_with_monitoring(
        builder=builder,
        runner=runner,
        environ=env,
        builder_kwargs=builder_kwargs,
    )


def validate_strict_paper_preflight(*, environ: Mapping[str, str] | None = None) -> dict:
    """Validate strict PAPER settings without building or starting any runtime.

    The result contains only non-secret policy values and is safe to display in
    a terminal or deployment log. This function never calls the engine builder
    or monitoring runner.
    """
    env = os.environ if environ is None else environ
    profile = str(env.get(PROFILE_ENV, "")).strip().lower()
    if profile != "strict":
        raise ValueError(
            f"{PROFILE_ENV}=strict is required; compatibility fallback is disabled"
        )
    config = resolve_paper_gate_profile(env)
    threshold = config["market_data_max_age_seconds"]
    if threshold is None:
        # Defensive assertion: strict resolver should always require this.
        raise ValueError(f"{MAX_AGE_ENV} is required for strict PAPER startup")
    return {
        "schema_version": 1,
        "status": "PASS",
        "profile": "strict",
        "configuration_validated": True,
        "execution_mode": "PAPER",
        "market_data_gate_required": True,
        "market_data_max_age_seconds": threshold,
        "runtime_started": False,
        "broker_orders_submitted": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint; ``--preflight`` validates settings without starting."""
    parser = argparse.ArgumentParser(
        description="Strict-profile PAPER launcher (no LIVE execution path)."
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="validate strict PAPER configuration and exit without starting runtime",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="with --preflight, print machine-readable JSON",
    )
    args = parser.parse_args(argv)
    if args.json and not args.preflight:
        parser.error("--json is supported only with --preflight")
    if args.preflight:
        try:
            result = validate_strict_paper_preflight()
        except (TypeError, ValueError) as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(
                "STRICT PAPER PREFLIGHT PASS: "
                f"max_age_seconds={result['market_data_max_age_seconds']}; "
                "runtime_started=False; broker_orders_submitted=False"
            )
        return 0
    run_strict_profiled_paper_launcher()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
