"""No-start preflight validates strict PAPER config without runtime side effects."""
import json
import os
import subprocess
import sys

import pytest

from core.runtime.paper_gate_profile import MAX_AGE_ENV, PROFILE_ENV
from core.runtime.strict_profiled_paper_launcher import validate_strict_paper_preflight


def test_valid_preflight_returns_policy_only_and_does_not_start_runtime():
    result = validate_strict_paper_preflight(
        environ={PROFILE_ENV: "strict", MAX_AGE_ENV: "12.5"}
    )
    assert result == {
        "schema_version": 1,
        "status": "PASS",
        "profile": "strict",
        "configuration_validated": True,
        "execution_mode": "PAPER",
        "market_data_gate_required": True,
        "market_data_max_age_seconds": 12.5,
        "runtime_started": False,
        "broker_orders_submitted": False,
    }


@pytest.mark.parametrize("environ", [
    {},
    {PROFILE_ENV: "compat", MAX_AGE_ENV: "15"},
    {PROFILE_ENV: "strict"},
    {PROFILE_ENV: "strict", MAX_AGE_ENV: "nan"},
    {PROFILE_ENV: "strict", MAX_AGE_ENV: "-0.1"},
])
def test_preflight_rejects_invalid_settings_without_runtime(environ):
    with pytest.raises(ValueError):
        validate_strict_paper_preflight(environ=environ)


def test_cli_preflight_json_succeeds_without_runtime_start():
    env = os.environ.copy()
    env[PROFILE_ENV] = "strict"
    env[MAX_AGE_ENV] = "7"
    completed = subprocess.run(
        [sys.executable, "-m", "core.runtime.strict_profiled_paper_launcher", "--preflight", "--json"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == 1
    assert payload["profile"] == "strict"
    assert payload["configuration_validated"] is True
    assert payload["status"] == "PASS"
    assert payload["market_data_max_age_seconds"] == 7.0
    assert payload["runtime_started"] is False
    assert payload["broker_orders_submitted"] is False


def test_cli_preflight_invalid_profile_fails_without_runtime_start():
    env = os.environ.copy()
    env.pop(PROFILE_ENV, None)
    env.pop(MAX_AGE_ENV, None)
    completed = subprocess.run(
        [sys.executable, "-m", "core.runtime.strict_profiled_paper_launcher", "--preflight"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 2
    assert f"{PROFILE_ENV}=strict is required" in completed.stderr
    assert "PREFLIGHT PASS" not in completed.stdout


def test_preflight_json_has_stable_policy_schema_and_no_environment_secrets():
    env = os.environ.copy()
    env[PROFILE_ENV] = "strict"
    env[MAX_AGE_ENV] = "9"
    env["DEMO_SECRET_SENTINEL"] = "never-print-this-value"
    completed = subprocess.run(
        [sys.executable, "-m", "core.runtime.strict_profiled_paper_launcher", "--preflight", "--json"],
        env=env, text=True, capture_output=True, check=False, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "never-print-this-value" not in completed.stdout
    assert "never-print-this-value" not in completed.stderr
    payload = json.loads(completed.stdout)
    assert set(payload) == {
        "schema_version", "status", "profile", "configuration_validated",
        "execution_mode", "market_data_gate_required",
        "market_data_max_age_seconds", "runtime_started",
        "broker_orders_submitted",
    }
    assert payload["schema_version"] == 1
    assert payload["runtime_started"] is False
    assert payload["broker_orders_submitted"] is False
