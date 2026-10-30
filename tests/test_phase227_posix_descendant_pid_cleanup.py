"""Verify POSIX audit timeout cleanup removes a real descendant process."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from scripts.phase222_test_audit import _run_one

pytestmark = pytest.mark.skipif(os.name == "nt", reason="requires POSIX process-group semantics")


def _process_is_alive(pid: int) -> bool:
    """Treat a Linux zombie as terminated; it cannot execute or retain resources."""
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        if proc_stat.exists():
            fields = proc_stat.read_text(encoding="ascii").split()
            if len(fields) > 2 and fields[2] == "Z":
                return False
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def test_timeout_terminates_real_descendant_pid(tmp_path: Path) -> None:
    marker = tmp_path / "descendant.pid"
    child_code = (
        "import os,time,pathlib; "
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()), encoding='ascii'); "
        "time.sleep(60)"
    )
    test_file = tmp_path / "test_hanging_parent.py"
    test_file.write_text(
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        f"deadline=time.monotonic()+5\nwhile not __import__('pathlib').Path({str(marker)!r}).exists() and time.monotonic()<deadline: time.sleep(0.02)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    result = _run_one(test_file, timeout_seconds=4.0)
    assert result["status"] == "timeout", result
    assert marker.exists(), f"fixture descendant did not start before timeout; audit={result!r}"
    pid = int(marker.read_text(encoding="ascii"))

    deadline = time.monotonic() + 4.0
    while _process_is_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _process_is_alive(pid), f"descendant PID {pid} survived timeout cleanup"
    assert result["duration_seconds"] < 11.0, result
