from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase222_test_audit.py"
spec = importlib.util.spec_from_file_location("phase222_test_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
assert spec.loader is not None
spec.loader.exec_module(audit)


def test_atomic_json_write_is_parseable_and_replaces_existing_file(tmp_path):
    target = tmp_path / "nested" / "report.json"
    audit._atomic_write_json(target, {"version": 1})
    audit._atomic_write_json(target, {"version": 2, "ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2, "ok": True}
    assert list(target.parent.glob("*.tmp")) == []


def test_classifies_no_tests_separately_from_failure():
    assert audit._classify(5, "no tests ran in 0.01s") == "no_tests"
    assert audit._classify(1, "AssertionError") == "failed"
    assert audit._classify(2, "ERROR collecting test_file.py") == "collection_error"
    assert audit._classify(0, "2 passed") == "passed"


def test_runs_a_passing_test_file_in_isolated_pytest(tmp_path):
    path = tmp_path / "test_smoke_phase222.py"
    path.write_text("""def test_smoke():\n    assert 2 + 2 == 4\n""", encoding="utf-8")
    result = audit._run_one(path, 15)
    assert result["status"] == "passed", result
    assert result["returncode"] == 0


def test_timeout_is_reported_and_does_not_corrupt_output(tmp_path):
    path = tmp_path / "test_slow_phase222.py"
    path.write_text("""import time\ndef test_slow():\n    time.sleep(8)\n""", encoding="utf-8")
    result = audit._run_one(path, 1.0)
    assert result["status"] == "timeout", result
    assert result["returncode"] is None
