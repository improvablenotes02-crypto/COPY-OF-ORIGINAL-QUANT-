"""Phase 197: packaged strategy provenance works without shipping .git."""
from __future__ import annotations
import json
from pathlib import Path

from core.research.historical_reconstruction import reconstruct_strategy_history

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_bundle_reconstructs_known_git_milestones_without_git_dir():
    bundle_path = ROOT / "reports" / "strategy_provenance_bundle.json"
    assert bundle_path.is_file()
    assert not (ROOT / ".git").exists()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["schema"] == "quantengine.strategy-provenance-bundle.v1"
    assert bundle["evidence_class"].startswith("source-derived, unsigned")
    report = reconstruct_strategy_history(ROOT)
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
