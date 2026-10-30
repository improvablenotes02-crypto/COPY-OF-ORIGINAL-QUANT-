"""Deployment smoke test for the strict PAPER preflight CLI.

Runs the actual module in fresh subprocesses, validates the allowlisted JSON
contract, and confirms that a compatibility profile is rejected. It never
constructs the trading engine or starts monitoring.

Usage: python scripts/strict_paper_preflight_smoke.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_ENV = "QE_PAPER_DATA_GATE_PROFILE"
MAX_AGE_ENV = "QE_PAPER_DATA_MAX_AGE_SECONDS"
EXPECTED_KEYS = {
    "schema_version", "status", "profile", "configuration_validated",
    "execution_mode", "market_data_gate_required",
    "market_data_max_age_seconds", "runtime_started",
    "broker_orders_submitted",
}


def _run(profile: str, max_age: str | None) -> subprocess.CompletedProcess[str]:
    # Deliberately use a small environment to prove the CLI does not depend on
    # unrelated shell variables or print them into its output.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        PROFILE_ENV: profile,
    }
    if max_age is not None:
        env[MAX_AGE_ENV] = max_age
    env["QE_PREFLIGHT_SENTINEL_SECRET"] = "do-not-echo-this-secret"
    return subprocess.run(
        [sys.executable, "-m", "core.runtime.strict_profiled_paper_launcher",
         "--preflight", "--json"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=30,
        check=False,
    )


def main() -> int:
    good = _run("strict", "15")
    if good.returncode != 0:
        raise SystemExit(f"strict preflight unexpectedly failed: {good.stderr.strip()}")
    try:
        payload = json.loads(good.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"strict preflight did not emit JSON: {exc}") from exc
    if set(payload) != EXPECTED_KEYS:
        raise SystemExit("preflight JSON keys differ from the version-1 allowlist")
    expected = {
        "schema_version": 1,
        "status": "PASS",
        "profile": "strict",
        "configuration_validated": True,
        "execution_mode": "PAPER",
        "market_data_gate_required": True,
        "market_data_max_age_seconds": 15.0,
        "runtime_started": False,
        "broker_orders_submitted": False,
    }
    if payload != expected:
        raise SystemExit(f"preflight policy payload mismatch: {payload!r}")
    if "do-not-echo-this-secret" in good.stdout + good.stderr:
        raise SystemExit("preflight leaked an unrelated environment secret")

    bad = _run("compat", "15")
    if bad.returncode == 0 or "PREFLIGHT PASS" in bad.stdout:
        raise SystemExit("compatibility profile unexpectedly passed strict preflight")
    if "do-not-echo-this-secret" in bad.stdout + bad.stderr:
        raise SystemExit("rejected preflight leaked an unrelated environment secret")
    print("STRICT_PAPER_PREFLIGHT_SMOKE_PASS")
    print("valid strict profile: schema and policy verified")
    print("compat profile: rejected")
    print("runtime_started=false; broker_orders_submitted=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
