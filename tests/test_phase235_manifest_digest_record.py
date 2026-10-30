from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qe_verify_release_candidate_phase235", ROOT / "scripts" / "verify_release_candidate.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_detached_record_requires_explicit_manifest_payload_digest_pass(tmp_path: Path) -> None:
    # Reuse the strict-record fixture, then remove the new required assurance.
    fixture_spec = importlib.util.spec_from_file_location(
        "qe_phase233_fixture", ROOT / "tests" / "test_phase233_strict_detached_record.py"
    )
    fixture_module = importlib.util.module_from_spec(fixture_spec)
    assert fixture_spec.loader is not None
    fixture_spec.loader.exec_module(fixture_module)
    artifact, record = fixture_module._fixture(tmp_path)
    text = record.read_text(encoding="utf-8")
    text = text.replace("Manifest payload digests: PASS\n", "")
    record.write_text(text, encoding="utf-8", newline="\n")
    try:
        MODULE.verify_detached_record(artifact, record)
    except RuntimeError as exc:
        assert "field mismatch" in str(exc)
    else:
        raise AssertionError("record must explicitly certify payload digest verification")
