"""Phase 229: release ZIPs are reproducible, not merely sorted."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fixture_tree(dst: Path) -> Path:
    root = dst / "source"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "generate_manifest.py", root / "scripts")
    shutil.copy2(ROOT / "scripts" / "build_release.py", root / "scripts")
    (root / "core").mkdir()
    (root / "core" / "sample.py").write_text("VALUE = 229\n", encoding="utf-8")
    (root / ".env.example").write_text("API_KEY=replace-me\n", encoding="utf-8")
    (root / ".env").write_text("API_KEY=must-not-ship\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("private metadata\n", encoding="utf-8")
    return root


def _build(root: Path, output: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "build_release.py"),
         "--root", str(root), "--output", str(output)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    assert "sha256:" in result.stdout
    return hashlib.sha256(output.read_bytes()).hexdigest()


def test_two_builds_have_identical_archive_bytes_and_metadata(tmp_path: Path) -> None:
    root = _fixture_tree(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_hash = _build(root, first)
    # Touch a source mtime: it must not affect the output archive hash.
    source = root / "core" / "sample.py"
    source.touch()
    second_hash = _build(root, second)

    assert first_hash == second_hash
    with zipfile.ZipFile(first) as z1, zipfile.ZipFile(second) as z2:
        assert z1.namelist() == z2.namelist()
        assert z1.testzip() is None and z2.testzip() is None
        assert z1.read("BUILD_MANIFEST.sha256") == z2.read("BUILD_MANIFEST.sha256")
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in z1.infolist())
        assert ".env" not in z1.namelist()
        assert ".git/config" not in z1.namelist()
        assert ".env.example" in z1.namelist()


def test_content_change_changes_archive_hash(tmp_path: Path) -> None:
    root = _fixture_tree(tmp_path)
    before = tmp_path / "before.zip"
    after = tmp_path / "after.zip"
    hash_before = _build(root, before)
    (root / "core" / "sample.py").write_text("VALUE = 230\n", encoding="utf-8")
    hash_after = _build(root, after)
    assert hash_before != hash_after
