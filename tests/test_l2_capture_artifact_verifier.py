"""Tests for the independent offline L2 capture artifact verifier."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_l2_capture_artifacts import CaptureVerificationError, verify_capture


class TestL2CaptureArtifactVerifier(unittest.TestCase):
    def _write_fixture(self, root: Path, *, accepted: bool = True) -> Path:
        raw = root / "raw.jsonl"
        record = {
            "receipt_mono_ns": 10,
            "receipt_utc_ns": 20,
            "raw": {"type": "ob_updates", "sy": "BTCUSD", "seq": 1, "ts": 30},
            "tracker_accepted": accepted,
        }
        raw_bytes = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        raw.write_bytes(raw_bytes)
        summary = {
            "raw_capture_file": raw.name,
            "raw_capture_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "total_bytes_written": len(raw_bytes),
            "total_raw_frames": 1,
            "rejected_frames_count": 0 if accepted else 1,
            "continuity_checks": {"zero_rejected_frames": accepted, "raw_capture_persistence_complete": True},
            "continuity_evidence_verdict": "VERIFIED_24H" if accepted else "PARTIAL",
        }
        path = root / "summary.json"
        path.write_text(json.dumps(summary), encoding="utf-8")
        return path

    def test_verifies_exact_hash_size_and_frame_count(self):
        with tempfile.TemporaryDirectory() as td:
            result = verify_capture(self._write_fixture(Path(td)))
        self.assertTrue(result["integrity_valid"])
        self.assertTrue(result["evidence_eligible"])
        self.assertEqual(result["raw_capture_frames"], 1)

    def test_detects_tampered_raw_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            (root / "raw.jsonl").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(CaptureVerificationError, "SHA-256"):
                verify_capture(summary)

    def test_partial_capture_integrity_can_be_valid_without_being_evidence_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            result = verify_capture(self._write_fixture(Path(td), accepted=False))
        self.assertTrue(result["integrity_valid"])
        self.assertFalse(result["evidence_eligible"])
        self.assertEqual(result["persisted_tracker_rejections"], 1)

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["raw_capture_file"] = "../raw.jsonl"
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "basename"):
                verify_capture(summary)

    def test_rejects_inconsistent_frame_count(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["total_raw_frames"] = 2
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "frame count"):
                verify_capture(summary)


if __name__ == "__main__":
    unittest.main()
