"""Controlled PAPER startup path using the deployment market-data profile.

This module is intentionally separate from frozen legacy ``main.py``. Call
``run_profiled_paper_with_monitoring`` from an explicitly selected PAPER
launcher to validate gate policy, build the canonical engine, and only then
hand that same engine to the monitoring/lifecycle runner.

It never selects LIVE mode and does not create broker order-write paths.
"""
from __future__ import annotations

from typing import Callable, Mapping

from core.runtime.paper_gate_profile import build_profiled_paper_engine


def run_profiled_paper_with_monitoring(
    *,
    builder: Callable | None = None,
    runner: Callable | None = None,
    environ: Mapping[str, str] | None = None,
    builder_kwargs: dict | None = None,
):
    """Validate profile before build; pass configured engine to the runner.

    ``runner`` defaults to the canonical PAPER monitoring lifecycle. Injectable
    dependencies allow deterministic offline startup/failure tests.
    Configuration errors propagate before either builder or runner is called.
    """
    engine, manager = build_profiled_paper_engine(
        builder=builder,
        environ=environ,
        **(builder_kwargs or {}),
    )
    if runner is None:
        from core.monitoring.service import run_paper_with_monitoring as runner
    return runner(engine), manager
