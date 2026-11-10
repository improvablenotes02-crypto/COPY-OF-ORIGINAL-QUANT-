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
            "raw": {"type": "ob_updates", "sy": "BTCUSD", "seq": 1, "ts": 30, "action": "snapshot", "b": [["99", "1"]], "a": [["101", "1"]]},
            "tracker_accepted": accepted,
        }
        raw_bytes = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        raw.write_bytes(raw_bytes)
        summary = {
            "raw_capture_file": raw.name,
            "raw_capture_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "total_bytes_written": len(raw_bytes),
            "total_raw_frames": 1,
            "duration_seconds": 86400 if accepted else 120,
            "rejected_frames_count": 0 if accepted else 1,
            "continuity_checks": {"zero_rejected_frames": accepted, "raw_capture_persistence_complete": True},
            "continuity_evidence_verdict": "VERIFIED_24H" if accepted else "PARTIAL",
            "symbol_quality": {"BTCUSD": {"total_messages": 1, "valid_updates": 1 if accepted else 0, "rejected_count": 0 if accepted else 1}},
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
        self.assertEqual(result["per_symbol_frame_counts"], {"BTCUSD": 1})

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


    
    def test_rejects_per_symbol_summary_count_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["symbol_quality"]["BTCUSD"]["total_messages"] = 2
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "total_messages mismatch"):
                verify_capture(summary)

    def test_rejects_accepted_update_without_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            record = json.loads(raw.read_text())
            record["raw"]["action"] = "update"
            raw_bytes = (json.dumps(record, sort_keys=True) + "\\n").encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "before an accepted snapshot"):
                verify_capture(summary)

    def test_rejects_non_increasing_monotonic_receipt_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            first = json.loads(raw.read_text())
            second = dict(first)
            second["receipt_mono_ns"] = first["receipt_mono_ns"]
            second["raw"] = dict(first["raw"], seq=2, action="update")
            second["tracker_accepted"] = True
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\\n") + (json.dumps(second, sort_keys=True) + "\\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "non-increasing monotonic"):
                verify_capture(summary)

    def test_rejects_accepted_sequence_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            first = json.loads(raw.read_text())
            second = dict(first)
            second["receipt_mono_ns"] = 11
            second["raw"] = dict(first["raw"], seq=3, action="update")
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\\n") + (json.dumps(second, sort_keys=True) + "\\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "sequence gap"):
                verify_capture(summary)

    def test_rejects_verified_verdict_with_short_duration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["duration_seconds"] = 60
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "short duration"):
                verify_capture(summary)

    def test_rejects_verified_verdict_with_rejected_frame_count(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["rejected_frames_count"] = 1
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "rejected frames"):
                verify_capture(summary)


if __name__ == "__main__":
    unittest.main()
