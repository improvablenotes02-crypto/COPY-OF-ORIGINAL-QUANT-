"""Helpers for current branch checks and historical Git provenance gates."""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Iterable

DEFAULT_EXPECTED_BRANCH = "main"
EXPECTED_BRANCH_ENV = "QUANTENGINE_EXPECTED_GIT_BRANCH"
ALLOWED_EXPECTED_BRANCHES = {
    "main",
    "recovery/phase238-missing-research-modules",
}

PINNED_ANCESTORS = {
    "N": "acab874d1a2cf256ab5f63a1b7fce5d061069b2d",
    "O": "5c95fd623f33eb79db7d195fb75c28ef8ac3739e",
    "P": "6a961459aed7051564c17a4ab88cdf0814ee5b1a",
    "Q": "e1483a1090ce04afb8533ced9f1d1acf6c542bff",
    "R": "bd21e9ac06b33857f2b314925f25e528ecf0ea2b",
    "S": "d77af19e8574b76f065ded1b2b2c09601aa110de",
    "T": "e235663d2a49a0272ee804c8da4759773ee0847f",
    "U": "0e4d3f04ce139dfd64c5819b63a63601c3793bd8",
}

HISTORICAL_PROVENANCE_NODEIDS = frozenset({
    "tests/test_researcher_11g_n.py::TestRepositoryHead::test_starting_head_ancestor",
    "tests/test_researcher_11g_n.py::TestRepositoryHead::test_branch_main",
    "tests/test_researcher_11g_o.py::TestRepositoryHead::test_starting_head_ancestor",
    "tests/test_researcher_11g_o.py::TestRepositoryHead::test_branch_main",
    "tests/test_researcher_11g_p.py::TestRepositoryHead::test_starting_head_ancestor",
    "tests/test_researcher_11g_p.py::TestRepositoryHead::test_branch_main",
    "tests/test_researcher_11g_q.py::TestStartingState::test_head_descends_from_p",
    "tests/test_researcher_11g_q.py::TestStartingState::test_branch_main",
    "tests/test_researcher_11g_r.py::TestStartingState::test_head_descends_from_q",
    "tests/test_researcher_11g_r.py::TestStartingState::test_branch_main",
    "tests/test_researcher_11g_s.py::TestStartingState::test_head_descends_from_r",
    "tests/test_researcher_11g_s.py::TestStartingState::test_branch_main",
    "tests/test_researcher_11g_t.py::TestStartingState::test_head_descends_from_s",
    "tests/test_researcher_11g_t.py::TestStartingState::test_branch_main",
    "tests/test_researcher_11g_u.py::TestStartingState::test_head_descends_from_t",
    "tests/test_researcher_11g_u.py::TestStartingState::test_branch_main",
})

_STRICT_HISTORICAL_GATE = False


class BlockedEvidence(RuntimeError):
    """Raised when a required Git fact cannot be established."""


class HistoricalCollectionError(AssertionError):
    """Raised when the dedicated gate does not collect exactly its checks."""


def configure_historical_gate(enabled: bool) -> None:
    global _STRICT_HISTORICAL_GATE
    _STRICT_HISTORICAL_GATE = enabled


def validate_historical_collection(items: Iterable) -> None:
    nodeids = [item.nodeid for item in items]
    marked = [
        item.nodeid for item in items
        if item.get_closest_marker("historical_git_provenance") is not None
    ]
    all_counts = Counter(nodeids)
    marked_counts = Counter(marked)
    expected = HISTORICAL_PROVENANCE_NODEIDS

    missing_tests = sorted(expected - set(all_counts))
    missing_markers = sorted(
        nodeid for nodeid in expected
        if nodeid in all_counts and marked_counts[nodeid] == 0
    )
    duplicate_nodes = sorted(
        nodeid for nodeid, count in all_counts.items() if count != 1
    )
    unexpected_marked = sorted(set(marked_counts) - expected)
    marked_duplicates = sorted(
        nodeid for nodeid, count in marked_counts.items() if count != 1
    )

    problems = []
    if missing_tests:
        problems.append("missing tests: %s" % ", ".join(missing_tests))
    if missing_markers:
        problems.append("missing provenance markers: %s" %
                        ", ".join(missing_markers))
    if duplicate_nodes:
        problems.append("duplicate node IDs: %s" % ", ".join(duplicate_nodes))
    if unexpected_marked:
        problems.append("unexpected marked tests: %s" %
                        ", ".join(unexpected_marked))
    if marked_duplicates:
        problems.append("duplicate marked tests: %s" %
                        ", ".join(marked_duplicates))
    if problems:
        raise HistoricalCollectionError("; ".join(problems))


def expected_branch(environ=None) -> str:
    env = os.environ if environ is None else environ
    branch = env.get(EXPECTED_BRANCH_ENV, DEFAULT_EXPECTED_BRANCH)
    if branch not in ALLOWED_EXPECTED_BRANCHES:
        raise ValueError(
            "%s must be exactly one of %s; got %r"
            % (EXPECTED_BRANCH_ENV, sorted(ALLOWED_EXPECTED_BRANCHES), branch)
        )
    return branch


def assert_branch_matches(actual: str, environ=None) -> None:
    expected = expected_branch(environ)
    if actual != expected:
        raise AssertionError(
            "expected Git branch %r, found %r" % (expected, actual)
        )


def _unavailable(case, message: str, strict: bool | None = None) -> None:
    strict_gate = _STRICT_HISTORICAL_GATE if strict is None else strict
    reason = "BLOCKED_EVIDENCE: " + message
    if strict_gate:
        case.fail(reason)
    case.skipTest(reason)


def assert_current_branch(case, root: Path) -> None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    if result.returncode != 0 or not result.stdout.strip():
        _unavailable(case, "current branch cannot be established: " +
                      (result.stderr.strip() or "Git returned no branch"))
    assert_branch_matches(result.stdout.strip())


def assert_historical_ancestor(case, commit: str, root: Path,
                               strict: bool | None = None,
                               head: str = "HEAD") -> None:
    object_check = subprocess.run(
        ["git", "cat-file", "-e", "%s^{commit}" % commit],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    if object_check.returncode != 0:
        _unavailable(
            case,
            "required commit %s is unavailable in this checkout" % commit,
            strict,
        )

    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, head],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    if ancestry.returncode == 0:
        return
    if ancestry.returncode == 1:
        case.fail("historical commit %s is not an ancestor of HEAD" % commit)
    case.fail(
        "could not verify ancestry for %s (git exit %d): %s"
        % (commit, ancestry.returncode, ancestry.stderr.strip())
    )
