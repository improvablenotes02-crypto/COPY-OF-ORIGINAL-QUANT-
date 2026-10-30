from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qe_verify_release_candidate_phase237", ROOT / "scripts" / "verify_release_candidate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _archive(path: Path, entries: dict[str, bytes]) -> Path:
    lines = []
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
            lines.append(f"{hashlib.sha256(payload).hexdigest()}  {name}\n")
        archive.writestr("BUILD_MANIFEST.sha256", "".join(lines))
    return path


def test_rejects_windows_reserved_device_names(tmp_path: Path) -> None:
    artifact = _archive(tmp_path / "reserved.zip", {"CON.txt": b"x"})
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "unsafe manifest path" in str(exc)
    else:
        raise AssertionError("Windows reserved device names must be rejected")


def test_rejects_ntfs_alternate_data_streams(tmp_path: Path) -> None:
    artifact = _archive(tmp_path / "ads.zip", {"report.txt:payload": b"x"})
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "unsafe manifest path" in str(exc)
    else:
        raise AssertionError("NTFS alternate data stream paths must be rejected")


def test_rejects_trailing_dot_or_space(tmp_path: Path) -> None:
    for name in ("report.", "report "):
        artifact = _archive(tmp_path / ("trailing-" + str(len(name)) + ".zip"), {name: b"x"})
        try:
            MODULE.verify_archive(artifact)
        except RuntimeError:
            pass  # either the explicit path guard or ZIP/manifest mismatch rejects it
        else:
            raise AssertionError("Windows-trimmed filenames must be rejected")


def test_rejects_case_insensitive_path_collisions(tmp_path: Path) -> None:
    artifact = _archive(tmp_path / "case-collision.zip", {"Data/A.txt": b"a", "data/a.TXT": b"b"})
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "case-insensitive manifest path collision" in str(exc)
    else:
        raise AssertionError("case-insensitive extraction collisions must be rejected")


def test_rejects_superscript_reserved_device_names(tmp_path: Path) -> None:
    for name in ("COM¹.log", "COM²", "COM³.txt", "LPT¹", "LPT².bin", "LPT³"):
        artifact = _archive(tmp_path / ("superscript-" + str(len(name)) + ".zip"), {name: b"x"})
        try:
            MODULE.verify_archive(artifact)
        except RuntimeError as exc:
            assert "unsafe manifest path" in str(exc)
        else:
            raise AssertionError("superscript DOS device names must be rejected")


def test_rejects_overlong_windows_path_component(tmp_path: Path) -> None:
    name = "a" * 256 + ".txt"
    artifact = _archive(tmp_path / "overlong-component.zip", {name: b"x"})
    try:
        MODULE.verify_archive(artifact)
    except RuntimeError as exc:
        assert "unsafe manifest path" in str(exc)
    else:
        raise AssertionError("overlong Windows path components must be rejected")


def test_accepts_portable_nested_unicode_path(tmp_path: Path) -> None:
    name = "reports/市場-data/summary-2026.txt"
    artifact = _archive(tmp_path / "unicode-portable.zip", {name: b"ok"})
    members, _ = MODULE.verify_archive(artifact)
    assert members == 2
