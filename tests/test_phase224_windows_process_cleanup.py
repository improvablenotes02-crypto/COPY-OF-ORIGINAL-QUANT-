"""Cross-platform unit checks for the Windows audit process-tree cleanup path.

These tests mock Windows-only primitives on non-Windows hosts; they do not claim
that native Windows process-tree termination has been exercised end-to-end.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase222_test_audit.py"
spec = importlib.util.spec_from_file_location("phase222_test_audit_phase224", SCRIPT)
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
assert spec.loader is not None
spec.loader.exec_module(audit)


class FakeProcess:
    pid = 4321

    def __init__(self):
        self.kill_called = False

    def kill(self):
        self.kill_called = True


def test_windows_cleanup_invokes_taskkill_tree_force(monkeypatch):
    calls = []
    monkeypatch.setattr(audit, "os", SimpleNamespace(name="nt"))

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    proc = FakeProcess()
    audit._terminate_process_tree(proc)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["taskkill", "/PID", "4321", "/T", "/F"]
    assert kwargs["timeout"] == 5
    assert kwargs["check"] is False
    assert proc.kill_called is False


def test_windows_cleanup_falls_back_to_direct_kill_if_taskkill_fails(monkeypatch):
    monkeypatch.setattr(audit, "os", SimpleNamespace(name="nt"))

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("taskkill", 5)

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    proc = FakeProcess()
    audit._terminate_process_tree(proc)
    assert proc.kill_called is True


def test_windows_cleanup_tolerates_missing_taskkill(monkeypatch):
    monkeypatch.setattr(audit, "os", SimpleNamespace(name="nt"))

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("taskkill unavailable")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    proc = FakeProcess()
    audit._terminate_process_tree(proc)
    assert proc.kill_called is True
