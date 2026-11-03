"""Phase 197: packaged strategy provenance works without shipping .git."""
from __future__ import annotations
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import zipfile

from core.research.historical_reconstruction import reconstruct_strategy_history
from core.research.strategy_identity import LEGACY_9_FILES

ROOT = Path(__file__).resolve().parents[1]
BUILD_RELEASE = ROOT / "scripts" / "build_release.py"
GENERATE_MANIFEST = ROOT / "scripts" / "generate_manifest.py"
MANIFEST_NAME = "BUILD_MANIFEST.sha256"


def _load_manifest_module():
    spec = importlib.util.spec_from_file_location(
        "phase197_generate_manifest", GENERATE_MANIFEST
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaged_bundle_reconstructs_known_git_milestones_without_git_dir():
    manifest_module = _load_manifest_module()
    package_inputs = [
        "scripts/build_release.py",
        "scripts/generate_manifest.py",
        "reports/strategy_provenance_bundle.json",
        *LEGACY_9_FILES,
    ]

    with tempfile.TemporaryDirectory(prefix="phase197-package-") as temp:
        temp_root = Path(temp)
        source = temp_root / "source"
        source.mkdir()
        for rel in package_inputs:
            target = source / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, target)

        git_metadata = source / ".git"
        git_metadata.mkdir()
        (git_metadata / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_metadata / "config").write_text("[core]\n", encoding="utf-8")

        archive_path = temp_root / "release.zip"
        subprocess.run(
            [
                sys.executable,
                str(BUILD_RELEASE),
                "--root",
                str(source),
                "--output",
                str(archive_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

        extracted = temp_root / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            members = set(archive.namelist())
            archive.extractall(extracted)

        assert not any(name == ".git" or name.startswith(".git/") for name in members)
        assert not (extracted / ".git").exists()
        assert "reports/strategy_provenance_bundle.json" in members
        assert MANIFEST_NAME in members
        assert set(package_inputs).issubset(members)

        manifest_path = extracted / MANIFEST_NAME
        manifest_bytes = manifest_path.read_bytes()
        assert b"\r" not in manifest_bytes
        assert manifest_bytes == manifest_module.generate(extracted).encode("utf-8")
        assert manifest_module.verify(extracted, manifest_path, strict=True) == []
        expected_members = set(manifest_module.package_files(extracted))
        assert members == expected_members | {MANIFEST_NAME}

        bundle = json.loads(
            (extracted / "reports" / "strategy_provenance_bundle.json").read_text(
                encoding="utf-8"
            )
        )
        assert bundle["schema"] == "quantengine.strategy-provenance-bundle.v1"
        assert bundle["evidence_class"].startswith("source-derived, unsigned")

        report = reconstruct_strategy_history(extracted)
        assert report["provenance_mode"] == "packaged_unsigned_source_derived_bundle"
        milestones = {item["name"]: item for item in report["milestones"]}
        assert milestones["Phase 14 Baseline Mint"]["composite_sha256_lf"] == (
            "db5bcdc01cd88b6c997e630e7ad1f6879f72f4ccc191393a6ff41675df52be72"
        )
        assert milestones["Phase 14 Runtime Boundary"]["composite_sha256_lf"] == (
            "9eff61b777846c7f5e2056c486c9c381872a93e154d35160e70f63051c8fd8a2"
        )
        assert milestones["Git HEAD (Current Branch)"]["commit"] == (
            "ffefa14a8729f6d2160db3735a06257cbb6ab48b"
        )


def test_bundle_does_not_claim_to_reconstruct_unavailable_historical_pin():
    bundle = json.loads(
        (ROOT / "reports" / "strategy_provenance_bundle.json").read_text(encoding="utf-8")
    )
    pin = bundle["historical_test_pin"]
    assert pin["sha256"] == "c52e648ca24fb03b9ba818ebb766e32b035b48df201d5a2a1b254d04f7f3d5a6"
    assert pin["status"] == "UNRECONSTRUCTED_FROM_AVAILABLE_BLOBS"
