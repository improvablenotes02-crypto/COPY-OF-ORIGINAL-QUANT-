from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qe_verify_release_candidate_phase234", ROOT / "scripts" / "verify_release_candidate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _archive(path: Path, payload: bytes, manifest: str | None = None) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    manifest = manifest if manifest is not None else f"{digest}  source.txt\n"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("source.txt", payload)
        archive.writestr("BUILD_MANIFEST.sha256", manifest)
    return path


def test_rejects_payload_that_does_not_match_manifest_hash(tmp_path: Path) -> None:
    artifact = tmp_path / "bad-hash.zip"
    original_digest = hashlib.sha256(b"expected\n").hexdigest()
    _archive(artifact, b"tampered\n", f"{original_digest}  source.txt\n")
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "manifest hash mismatch: source.txt" in str(exc)
    else:
        raise AssertionError("manifest hash mismatch must fail archive verification")


def test_rejects_duplicate_manifest_path(tmp_path: Path) -> None:
    artifact = tmp_path / "duplicate-path.zip"
    digest = hashlib.sha256(b"source\n").hexdigest()
    _archive(artifact, b"source\n", f"{digest}  source.txt\n{digest}  source.txt\n")
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "duplicate manifest path" in str(exc)
    else:
        raise AssertionError("duplicate manifest path must be rejected")


def test_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    artifact = tmp_path / "path-traversal.zip"
    _archive(artifact, b"source\n", f"{hashlib.sha256(b'source\\n').hexdigest()}  ../source.txt\n")
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "unsafe manifest path" in str(exc)
    else:
        raise AssertionError("path traversal in manifest must be rejected")


def test_accepts_matching_manifest_hashes(tmp_path: Path) -> None:
    artifact = tmp_path / "good.zip"
    _archive(artifact, b"valid\n")
    members, names = MODULE.verify_archive(artifact)
    assert members == 2
    assert set(names) == {"source.txt", "BUILD_MANIFEST.sha256"}


def test_rejects_windows_drive_qualified_manifest_path(tmp_path: Path) -> None:
    artifact = tmp_path / "windows-drive-path.zip"
    digest = hashlib.sha256(b"source\\n").hexdigest()
    _archive(artifact, b"source\\n", f"{digest}  C:/outside/source.txt\\n")
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "unsafe manifest path" in str(exc)
    else:
        raise AssertionError("Windows drive-qualified manifest paths must be rejected")


def test_rejects_control_character_in_manifest_path(tmp_path: Path) -> None:
    artifact = tmp_path / "control-character-path.zip"
    digest = hashlib.sha256(b"source\\n").hexdigest()
    _archive(artifact, b"source\\n", f"{digest}  source\\t.txt\\n")
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "unsafe manifest path" in str(exc)
    else:
        raise AssertionError("control characters in manifest paths must be rejected")
