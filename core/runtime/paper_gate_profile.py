"""Deployment profile for canonical paper-runtime market-data gating.

QE_PAPER_DATA_GATE_PROFILE accepts ``compat`` (default) or ``strict``.
QE_PAPER_DATA_MAX_AGE_SECONDS supplies the maximum accepted candle age.
Strict mode requires that threshold and fails startup if absent or invalid.
This profile configures the canonical paper startup path; it does not wrap
legacy direct constructors or claim universal enforcement across the codebase.
"""
from __future__ import annotations

import os
from typing import Mapping

from core.exchanges.paper_data_gate_policy import validate_paper_data_gate_config

PROFILE_ENV = "QE_PAPER_DATA_GATE_PROFILE"
MAX_AGE_ENV = "QE_PAPER_DATA_MAX_AGE_SECONDS"


def resolve_paper_gate_profile(environ: Mapping[str, str] | None = None) -> dict:
    """Return validated constructor kwargs for the canonical PAPER entrypoint."""
    env = os.environ if environ is None else environ
    raw_profile = env.get(PROFILE_ENV, "compat")
    profile = str(raw_profile).strip().lower()
    if profile not in {"compat", "strict"}:
        raise ValueError(f"{PROFILE_ENV} must be 'compat' or 'strict'")

    raw_age = env.get(MAX_AGE_ENV)
    if raw_age is not None and not str(raw_age).strip():
        raw_age = None
    required = profile == "strict"
    threshold = validate_paper_data_gate_config(
        raw_age,
        required=required,
    )
    return {
        "market_data_max_age_seconds": threshold,
        "market_data_gate_required": required,
    }


def build_profiled_paper_engine(*args, builder=None, environ=None, **kwargs):
    """Build the canonical paper engine with the selected deployment profile.

    This wrapper intentionally lives outside frozen legacy startup modules.
    It validates the profile before constructing anything, then applies the
    validated settings before the caller starts/reconciles the engine. Use this
    function explicitly from deployment startup when strict mode is desired.
    """
    config = resolve_paper_gate_profile(environ)
    if builder is None:
        from core.runtime.paper_main import build_paper_engine as builder
    engine, manager = builder(*args, **kwargs)
    # RealTimeEngine's constructor initializes these fields in compatibility
    # mode. Assign before the returned engine is started or reconciled.
    engine.market_data_max_age_seconds = config["market_data_max_age_seconds"]
    engine.market_data_gate_required = config["market_data_gate_required"]
    engine.market_data_now_provider = None
    return engine, manager
