"""Phase 194 regression tests for re-entrant cross-instance file locks."""
from pathlib import Path

from core.execution.testnet_authorization_gate import CrossProcessFileLock


def test_different_instances_release_original_owner_when_outer_releases_first(tmp_path: Path):
    lock_path = tmp_path / "shared.lock"
    outer = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)
    inner = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)

    outer.acquire()
    inner.acquire()
    outer.release()
    inner.release()

    # A leaked owner descriptor made this acquisition time out before Phase 194.
    probe = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)
    probe.acquire()
    probe.release()


def test_different_instances_release_original_owner_when_inner_releases_first(tmp_path: Path):
    lock_path = tmp_path / "shared.lock"
    outer = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)
    inner = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)

    outer.acquire()
    inner.acquire()
    inner.release()
    outer.release()

    probe = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)
    probe.acquire()
    probe.release()


def test_same_instance_reentrant_lock_stays_held_until_final_release(tmp_path: Path):
    lock_path = tmp_path / "shared.lock"
    lock = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)

    lock.acquire()
    lock.acquire()
    lock.release()

    # Another instance in the same thread is treated as re-entrant by design;
    # after one release, the final hold remains owned by the original lock.
    nested = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)
    nested.acquire()
    nested.release()
    lock.release()

    probe = CrossProcessFileLock(lock_path, timeout_seconds=0.2, poll_interval=0.005)
    probe.acquire()
    probe.release()
