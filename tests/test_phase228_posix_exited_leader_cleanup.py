"""Verify process-group cleanup after the group leader has already exited."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.phase222_test_audit import _terminate_process_tree

pytestmark = pytest.mark.skipif(os.name == "nt", reason="requires POSIX process-group semantics")


def _pid_is_executing(pid: int) -> bool:
    """Return false for missing processes and Linux zombies (which cannot execute)."""
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        if stat_path.exists():
            stat = stat_path.read_text(encoding="ascii")
            # comm is parenthesized and may contain spaces; state follows its final ')'.
            tail = stat[stat.rfind(")") + 2 :].split()
            if tail and tail[0] == "Z":
                return False
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def test_cleanup_kills_descendant_after_group_leader_exits(tmp_path: Path) -> None:
    marker = tmp_path / "descendant.pid"
    child_code = (
        "import os,time,pathlib; "
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()), encoding='ascii'); "
        "signal_ignored=False; time.sleep(60)"
    )
    leader_code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]);"
    )
    leader = subprocess.Popen(
        [sys.executable, "-c", leader_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    assert leader.wait(timeout=3.0) == 0
    deadline = time.monotonic() + 3.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists(), "fixture descendant did not start"
    pid = int(marker.read_text(encoding="ascii"))

    # Simulate timeout cleanup after the process-group leader has exited.
    _terminate_process_tree(leader)
    deadline = time.monotonic() + 3.0
    while _pid_is_executing(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _pid_is_executing(pid), f"descendant PID {pid} survived group cleanup"
    if leader.stdout is not None:
        leader.stdout.close()
