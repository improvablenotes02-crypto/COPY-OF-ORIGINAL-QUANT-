from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qe_verify_release_candidate", ROOT / "scripts" / "verify_release_candidate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _fixture_archive(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_secret_member_policy_is_case_insensitive_and_allows_template() -> None:
    assert MODULE.prohibited_member(".env")
    assert MODULE.prohibited_member("nested/.ENV.production")
    assert MODULE.prohibited_member("keys/private.KEY")
    assert MODULE.prohibited_member("nested/api_credentials.json")
    assert not MODULE.prohibited_member(".env.example")
    assert not MODULE.prohibited_member("docs/credential-handling.md")


def test_archive_rejects_secret_like_member(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    manifest = ""  # Member validation should fail before manifest coverage.
    _fixture_archive(archive, {"BUILD_MANIFEST.sha256": manifest.encode(), "nested/.env.prod": b"x"})
    try:
        MODULE.verify_archive(archive)
    except RuntimeError as exc:
        assert "prohibited secret-like members" in str(exc)
    else:
        raise AssertionError("secret-like archive member was accepted")


def test_archive_requires_manifest_coverage_match(tmp_path: Path) -> None:
    archive = tmp_path / "mismatch.zip"
    _fixture_archive(archive, {"BUILD_MANIFEST.sha256": b"", "unexpected.txt": b"x"})
    try:
        MODULE.verify_archive(archive)
    except RuntimeError as exc:
        assert "coverage mismatch" in str(exc)
    else:
        raise AssertionError("manifest coverage mismatch was accepted")
