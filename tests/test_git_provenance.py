from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import pytest

try:
    from tests import git_provenance as provenance
    from tests import conftest as pytest_hooks
    from tests import evidence_mode
except ImportError:
    import git_provenance as provenance
    import conftest as pytest_hooks
    import evidence_mode


class _Case:
    def skipTest(self, reason):
        raise unittest.SkipTest(reason)

    def fail(self, reason):
        raise AssertionError(reason)


class _FakeItem:
    def __init__(self, nodeid, marked=True):
        self.nodeid = nodeid
        self.marked = marked

    def get_closest_marker(self, name):
        return object() if self.marked and name == "historical_git_provenance" else None


class _FakeConfig:
    def getoption(self, name):
        assert name == "--historical-git-gate"
        return True


class _FakeSession:
    def __init__(self, items=()):
        self.items = list(items)
        self.config = _FakeConfig()


class _GateExit(Exception):
    def __init__(self, message, returncode):
        super().__init__(message)
        self.returncode = returncode


def _raise_gate_exit(message, returncode=0):
    raise _GateExit(message, returncode)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _make_repo(root: Path) -> str:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "QuantEngine test")
    _git(root, "config", "user.email", "quantengine-test@example.invalid")
    (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "initial")
    return _git(root, "rev-parse", "HEAD")


def test_main_is_the_default_expected_branch():
    assert provenance.expected_branch(environ={}) == "main"
    provenance.assert_branch_matches("main", environ={})


def test_recovery_branch_is_rejected_by_default():
    with pytest.raises(AssertionError, match="expected Git branch 'main'"):
        provenance.assert_branch_matches(
            "recovery/phase238-missing-research-modules", environ={}
        )


def test_recovery_branch_requires_exact_configuration():
    env = {
        provenance.EXPECTED_BRANCH_ENV:
            "recovery/phase238-missing-research-modules"
    }
    assert provenance.expected_branch(env) == env[provenance.EXPECTED_BRANCH_ENV]
    provenance.assert_branch_matches(
        "recovery/phase238-missing-research-modules", environ=env
    )


def test_arbitrary_expected_branch_is_rejected():
    with pytest.raises(ValueError, match="must be exactly one of"):
        provenance.expected_branch({
            provenance.EXPECTED_BRANCH_ENV: "feature/anything"
        })


def test_missing_pin_is_blocked_in_ordinary_mode(tmp_path):
    _make_repo(tmp_path / "repo")
    with pytest.raises(unittest.SkipTest, match="BLOCKED_EVIDENCE"):
        provenance.assert_historical_ancestor(
            _Case(), "f" * 40, tmp_path / "repo", strict=False
        )


def test_missing_pin_fails_closed_in_historical_gate(tmp_path):
    _make_repo(tmp_path / "repo")
    with pytest.raises(AssertionError, match="BLOCKED_EVIDENCE"):
        provenance.assert_historical_ancestor(
            _Case(), "f" * 40, tmp_path / "repo", strict=True
        )


def test_authentic_fixture_ancestor_passes(tmp_path):
    root = tmp_path / "repo"
    ancestor = _make_repo(root)
    (root / "tracked.txt").write_text("second\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "child")
    provenance.assert_historical_ancestor(_Case(), ancestor, root, strict=True)


def test_existing_unrelated_commit_fails_ancestry(tmp_path):
    root = tmp_path / "repo"
    ancestor = _make_repo(root)
    empty_tree = subprocess.run(
        ["git", "hash-object", "-t", "tree", "--stdin"],
        cwd=str(root),
        input=b"",
        capture_output=True,
        check=True,
    ).stdout.decode("ascii").strip()
    unrelated = _git(root, "commit-tree", empty_tree, "-m", "unrelated")
    assert unrelated != ancestor
    with pytest.raises(AssertionError, match="is not an ancestor"):
        provenance.assert_historical_ancestor(
            _Case(), ancestor, root, strict=True, head=unrelated
        )


def test_all_eight_historical_pins_are_unchanged():
    assert provenance.PINNED_ANCESTORS == {
        "N": "acab874d1a2cf256ab5f63a1b7fce5d061069b2d",
        "O": "5c95fd623f33eb79db7d195fb75c28ef8ac3739e",
        "P": "6a961459aed7051564c17a4ab88cdf0814ee5b1a",
        "Q": "e1483a1090ce04afb8533ced9f1d1acf6c542bff",
        "R": "bd21e9ac06b33857f2b314925f25e528ecf0ea2b",
        "S": "d77af19e8574b76f065ded1b2b2c09601aa110de",
        "T": "e235663d2a49a0272ee804c8da4759773ee0847f",
        "U": "0e4d3f04ce139dfd64c5819b63a63601c3793bd8",
    }


def _expected_items():
    return [_FakeItem(nodeid) for nodeid in sorted(
        provenance.HISTORICAL_PROVENANCE_NODEIDS
    )]


def _assert_gate_collection_fails(items, match, monkeypatch):
    monkeypatch.setattr(pytest_hooks.pytest, "exit", _raise_gate_exit)
    with pytest.raises(_GateExit) as exc_info:
        pytest_hooks.pytest_collection_finish(_FakeSession(items))
    assert exc_info.value.returncode == 1
    assert match in str(exc_info.value)


def test_dedicated_gate_accepts_exactly_all_16_marked_nodes():
    items = _expected_items()
    provenance.validate_historical_collection(items)
    assert len(items) == 16


def test_dedicated_gate_fails_when_a_required_marker_is_removed(monkeypatch):
    items = _expected_items()
    items[0].marked = False
    _assert_gate_collection_fails(items, "missing provenance markers", monkeypatch)


def test_dedicated_gate_fails_when_a_required_test_is_not_collected(monkeypatch):
    items = _expected_items()[1:]
    _assert_gate_collection_fails(items, "missing tests", monkeypatch)


def test_dedicated_gate_fails_for_duplicate_or_renamed_node_ids():
    items = _expected_items()
    items[0].nodeid = "tests/test_researcher_11g_n.py::TestRepositoryHead::test_renamed"
    items.append(_FakeItem(items[1].nodeid))
    with pytest.raises(provenance.HistoricalCollectionError) as exc_info:
        provenance.validate_historical_collection(items)
    assert "missing tests" in str(exc_info.value)
    assert "unexpected marked tests" in str(exc_info.value)
    assert "duplicate node IDs" in str(exc_info.value)


def test_collection_hook_exits_nonzero_for_incomplete_gate(monkeypatch):
    items = _expected_items()[:-1]
    _assert_gate_collection_fails(
        items, "HISTORICAL_GATE_COLLECTION_FAILED", monkeypatch
    )


def test_strict_gate_rejects_source_archive_before_provenance_tests(monkeypatch):
    monkeypatch.setattr(
        evidence_mode,
        "detect_mode",
        lambda root: (evidence_mode.MODE_SOURCE_ARCHIVE, {"root": str(root)}),
    )
    monkeypatch.setattr(pytest_hooks.pytest, "exit", _raise_gate_exit)
    with pytest.raises(_GateExit) as exc_info:
        pytest_hooks.pytest_sessionstart(_FakeSession())
    assert exc_info.value.returncode == 1
    assert "requires a valid Git checkout" in str(exc_info.value)


def test_strict_evidence_guard_fails_instead_of_skipping(monkeypatch):
    monkeypatch.setattr(
        evidence_mode,
        "detect_mode",
        lambda: (evidence_mode.MODE_SOURCE_ARCHIVE, {}),
    )
    evidence_mode.configure_strict_git_evidence(True)
    try:
        with pytest.raises(AssertionError, match="BLOCKED_EVIDENCE"):
            evidence_mode.require_git_fact(
                _Case(), "simulated-source-archive-provenance"
            )
    finally:
        evidence_mode.configure_strict_git_evidence(False)


def test_ordinary_evidence_guard_still_skips_blocked_archive_fact(monkeypatch):
    monkeypatch.setattr(
        evidence_mode,
        "detect_mode",
        lambda: (evidence_mode.MODE_SOURCE_ARCHIVE, {}),
    )
    evidence_mode.configure_strict_git_evidence(False)
    with pytest.raises(unittest.SkipTest, match="BLOCKED_EVIDENCE"):
        evidence_mode.require_git_fact(
            _Case(), "simulated-source-archive-provenance"
        )
