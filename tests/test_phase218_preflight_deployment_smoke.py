"""Phase 218 regression tests for the deployment-facing preflight smoke check."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_deployment_smoke_checks_real_cli_in_isolated_subprocesses():
    result = subprocess.run(
        [sys.executable, "scripts/strict_paper_preflight_smoke.py"],
        cwd=ROOT, text=True, capture_output=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "STRICT_PAPER_PREFLIGHT_SMOKE_PASS" in result.stdout
    assert "compat profile: rejected" in result.stdout
