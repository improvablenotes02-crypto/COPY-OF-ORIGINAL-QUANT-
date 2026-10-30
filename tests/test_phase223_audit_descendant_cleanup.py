"""Regression coverage for pytest descendants retaining captured output pipes."""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase222_test_audit.py"
spec = importlib.util.spec_from_file_location("phase222_test_audit_phase223", SCRIPT)
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
assert spec.loader is not None
spec.loader.exec_module(audit)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal behavior is required for this regression")
def test_timeout_kills_descendant_that_ignores_sigterm_and_holds_pipe(tmp_path):
    test_file = tmp_path / "test_descendant_pipe.py"
    test_file.write_text(
        "import subprocess, sys, time\n"
        "def test_descendant_keeps_pipe_open():\n"
        "    subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(20)'])\n"
        "    time.sleep(20)\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    result = audit._run_one(test_file, 0.8)
    elapsed = time.monotonic() - started

    assert result["status"] == "timeout", result
    assert elapsed < 6.0, f"audit did not bound descendant cleanup: {elapsed:.2f}s"
