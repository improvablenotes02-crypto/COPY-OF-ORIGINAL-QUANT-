"""Native Windows integration test for bounded-audit descendant cleanup.

This test is intentionally skipped on non-Windows hosts. Mocks cannot establish
that taskkill actually terminates a real descendant process on Windows.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

from scripts.phase222_test_audit import _run_one

pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires native Windows process-tree semantics")


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def test_native_windows_timeout_terminates_real_descendant_process_tree():
    with tempfile.TemporaryDirectory(prefix="qe_phase225_windows_") as tmp:
        root = Path(tmp)
        marker = root / "descendant.pid"
        child_code = (
            "import os,time,pathlib; "
            f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()), encoding='ascii'); "
            "time.sleep(120)"
        )
        test_file = root / "test_hanging_parent.py"
        test_file.write_text(
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            f"deadline = time.monotonic() + 8\n"
            f"while not __import__('pathlib').Path({str(marker)!r}).exists() and time.monotonic() < deadline: time.sleep(0.02)\n"
            "time.sleep(120)\n",
            encoding="utf-8",
        )

        result = _run_one(test_file, timeout_seconds=2.0)
        assert result["status"] == "timeout", result
        assert marker.exists(), "fixture child did not start before timeout"
        child_pid = int(marker.read_text(encoding="ascii"))

        deadline = time.monotonic() + 5.0
        while _pid_is_running(child_pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _pid_is_running(child_pid), f"descendant process {child_pid} survived cleanup"
        assert result["duration_seconds"] < 12.0, result
