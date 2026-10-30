from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qe_verify_release_candidate_phase232", ROOT / "scripts" / "verify_release_candidate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _valid_archive(path: Path) -> int:
    payload = b"test source payload\n"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = f"{digest}  source.txt\n"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("source.txt", payload)
        archive.writestr("BUILD_MANIFEST.sha256", manifest)
    return 2


def _record(artifact: Path, members: int) -> Path:
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    record = artifact.with_suffix(artifact.suffix + ".sha256.txt")
    record.write_text(
        "QuantEngine CI release candidate verification\n"
        f"Artifact: {artifact.name}\nSHA-256: {digest}\n"
        f"Bytes: {artifact.stat().st_size}\nArchive members: {members}\n"
        "Reproducible second build: PASS\nZIP integrity: PASS\n"
        "Manifest coverage: PASS\nManifest payload digests: PASS\nSecret-file exclusion: PASS\n",
        encoding="utf-8", newline="\n",
    )
    return record


def test_detached_record_verifies_exact_archive(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.zip"
    members = _valid_archive(artifact)
    record = _record(artifact, members)
    result = MODULE.verify_detached_record(artifact, record)
    assert result["detached_record"] == "PASS"
    assert result["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()


def test_detached_record_rejects_tampered_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.zip"
    members = _valid_archive(artifact)
    record = _record(artifact, members)
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    try:
        MODULE.verify_detached_record(artifact, record)
    except RuntimeError as exc:
        assert "SHA-256" in str(exc) or "ZIP" in str(exc)
    else:
        raise AssertionError("tampered artifact was accepted")


def test_detached_record_rejects_wrong_artifact_name(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.zip"
    members = _valid_archive(artifact)
    record = _record(artifact, members)
    renamed = tmp_path / "renamed.zip"
    renamed.write_bytes(artifact.read_bytes())
    try:
        MODULE.verify_detached_record(renamed, record)
    except RuntimeError as exc:
        assert "name mismatch" in str(exc)
    else:
        raise AssertionError("record for a different artifact name was accepted")
