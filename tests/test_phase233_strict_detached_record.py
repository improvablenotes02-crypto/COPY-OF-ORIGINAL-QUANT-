from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qe_verify_release_candidate_phase233", ROOT / "scripts" / "verify_release_candidate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    import zipfile
    artifact = tmp_path / "candidate.zip"
    payload = b"fixture\n"
    digest = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("source.txt", payload)
        archive.writestr("BUILD_MANIFEST.sha256", f"{digest}  source.txt\n")
    record = artifact.with_suffix(".zip.sha256.txt")
    record.write_text(
        "QuantEngine CI release candidate verification\n"
        f"Artifact: {artifact.name}\nSHA-256: {hashlib.sha256(artifact.read_bytes()).hexdigest()}\n"
        f"Bytes: {artifact.stat().st_size}\nArchive members: 2\n"
        "Reproducible second build: PASS\nZIP integrity: PASS\n"
        "Manifest coverage: PASS\nManifest payload digests: PASS\nSecret-file exclusion: PASS\n",
        encoding="utf-8", newline="\n",
    )
    return artifact, record


def test_rejects_duplicate_sha256_field(tmp_path: Path) -> None:
    artifact, record = _fixture(tmp_path)
    record.write_text(record.read_text(encoding="utf-8") +
                       "SHA-256: forged\n", encoding="utf-8")
    try:
        MODULE.verify_detached_record(artifact, record)
    except RuntimeError as exc:
        assert "duplicate detached-record field" in str(exc)
    else:
        raise AssertionError("duplicate field must not override the trusted value")


def test_rejects_missing_verification_field(tmp_path: Path) -> None:
    artifact, record = _fixture(tmp_path)
    record.write_text(record.read_text(encoding="utf-8").replace(
        "Manifest coverage: PASS\n", ""), encoding="utf-8")
    try:
        MODULE.verify_detached_record(artifact, record)
    except RuntimeError as exc:
        assert "field mismatch" in str(exc)
    else:
        raise AssertionError("incomplete verification record must be rejected")


def test_rejects_invalid_record_header(tmp_path: Path) -> None:
    artifact, record = _fixture(tmp_path)
    record.write_text(record.read_text(encoding="utf-8").replace(
        "QuantEngine CI release candidate verification", "Other record", 1),
        encoding="utf-8")
    try:
        MODULE.verify_detached_record(artifact, record)
    except RuntimeError as exc:
        assert "header" in str(exc)
    else:
        raise AssertionError("invalid record header must be rejected")
