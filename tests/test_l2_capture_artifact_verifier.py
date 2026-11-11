"""Tests for the independent offline L2 capture artifact verifier."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_l2_capture_artifacts import CaptureVerificationError, verify_capture


class TestL2CaptureArtifactVerifier(unittest.TestCase):
    def _write_fixture(self, root: Path, *, accepted: bool = True) -> Path:
        raw = root / "raw.jsonl"
        record = {
            "connection_epoch": 0,
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
            "connection_epoch_count": 1,
            "accepted_snapshots_by_epoch": {"0": {"BTCUSD": 1}} if accepted else {},
            "duration_seconds": 86400 if accepted else 120,
            "reconnect_count": 0,
            "malformed_frames_count": 0,
            "rejected_frames_count": 0 if accepted else 1,
            "unexpected_frames_count": 0,
            "persistence_errors_count": 0,
            "freshness_violations_count": 0,
            "freshness_violations_by_symbol": {"BTCUSD": 0},
            "raw_capture_persistence_complete": True,
            "continuity_checks": {
                "minimum_24h_duration": accepted,
                "zero_transport_reconnects": True,
                "zero_malformed_frames": True,
                "zero_rejected_frames": accepted,
                "zero_unexpected_frames": True,
                "zero_persistence_errors": True,
                "zero_symbol_freshness_violations": True,
                "raw_capture_persistence_complete": True,
                "all_symbol_books_valid": accepted,
                "not_operator_or_safety_stopped": True,
            },
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

    def test_rejects_snapshot_evidence_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["accepted_snapshots_by_epoch"] = {"0": {"BTCUSD": 2}}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "snapshot evidence does not match"):
                verify_capture(summary)

    def test_rejects_invalid_snapshot_epoch_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["accepted_snapshots_by_epoch"] = {"00": {"BTCUSD": 1}}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "invalid epoch key"):
                verify_capture(summary)

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
            raw_bytes = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
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
            second["receipt_mono_ns"] = first["receipt_mono_ns"] - 1
            second["raw"] = dict(first["raw"], seq=2, action="update")
            second["tracker_accepted"] = True
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\n") + (json.dumps(second, sort_keys=True) + "\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "non-increasing monotonic"):
                verify_capture(summary)


    def test_rejects_duplicate_monotonic_receipt_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            first = json.loads(raw.read_text())
            second = dict(first)
            second["raw"] = dict(first["raw"], seq=2, action="update")
            second["tracker_accepted"] = True
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\n") + (json.dumps(second, sort_keys=True) + "\n")).encode("utf-8")
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
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\n") + (json.dumps(second, sort_keys=True) + "\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "sequence gap"):
                verify_capture(summary)


    def test_rejects_accepted_update_as_first_frame_after_reconnect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            first = json.loads(raw.read_text())
            second = dict(first)
            second["connection_epoch"] = 1
            second["receipt_mono_ns"] = 11
            second["raw"] = dict(first["raw"], seq=2, action="update")
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\n") + (json.dumps(second, sort_keys=True) + "\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["connection_epoch_count"] = 2
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "before an accepted snapshot"):
                verify_capture(summary)


    def test_rejects_snapshot_sequence_regression_across_connection_epochs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            first = json.loads(raw.read_text())
            first["raw"]["seq"] = 10
            second = dict(first)
            second["connection_epoch"] = 1
            second["receipt_mono_ns"] = 11
            second["raw"] = dict(first["raw"], seq=9, action="snapshot")
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\n") + (json.dumps(second, sort_keys=True) + "\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["connection_epoch_count"] = 2
            data["accepted_snapshots_by_epoch"] = {"0": {"BTCUSD": 1}, "1": {"BTCUSD": 1}}
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "snapshot sequence regression across connection epochs"):
                verify_capture(summary)

    def test_allows_non_regressing_snapshot_sequence_after_reconnect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            first = json.loads(raw.read_text())
            first["raw"]["seq"] = 10
            second = dict(first)
            second["connection_epoch"] = 1
            second["receipt_mono_ns"] = 11
            second["raw"] = dict(first["raw"], seq=10, action="snapshot")
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\n") + (json.dumps(second, sort_keys=True) + "\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["connection_epoch_count"] = 2
            data["accepted_snapshots_by_epoch"] = {"0": {"BTCUSD": 1}, "1": {"BTCUSD": 1}}
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            result = verify_capture(summary)
            self.assertTrue(result["integrity_valid"])

    def test_allows_empty_connection_epoch_between_persisted_epochs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            first = json.loads(raw.read_text())
            second = dict(first)
            second["connection_epoch"] = 2
            second["receipt_mono_ns"] = 11
            second["raw"] = dict(first["raw"], seq=1, action="snapshot")
            raw_bytes = ((json.dumps(first, sort_keys=True) + "\n") + (json.dumps(second, sort_keys=True) + "\n")).encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["total_raw_frames"] = 2
            data["connection_epoch_count"] = 3
            data["symbol_quality"]["BTCUSD"] = {"total_messages": 2, "valid_updates": 2, "rejected_count": 0}
            summary.write_text(json.dumps(data))
            result = verify_capture(summary)
        self.assertTrue(result["integrity_valid"])

    def test_rejects_frame_epoch_outside_summary_connection_count(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            record = json.loads(raw.read_text())
            record["connection_epoch"] = 1
            raw_bytes = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["connection_epoch_count"] = 1
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "exceeds summary connection count"):
                verify_capture(summary)

    def test_rejects_regressing_connection_epoch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            record = json.loads(raw.read_text())
            record["connection_epoch"] = 0
            raw_bytes = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            data["connection_epoch_count"] = 1
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "duplicate or regressing"):
                verify_capture(summary)


    def test_rejects_summary_persistence_flag_conflicting_with_continuity_checks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["raw_capture_persistence_complete"] = False
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "raw_capture_persistence_complete conflicts"):
                verify_capture(summary)

    def test_rejects_counter_conflicting_with_derived_continuity_check(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["persistence_errors_count"] = 1
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "persistence_errors_count conflicts"):
                verify_capture(summary)

    def test_rejects_per_symbol_freshness_counter_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["freshness_violations_count"] = 1
            data["continuity_checks"]["zero_symbol_freshness_violations"] = False
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "Per-symbol freshness counters do not sum"):
                verify_capture(summary)

    def test_rejects_non_string_order_book_action_without_type_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            record = json.loads(raw.read_text())
            record["raw"]["action"] = ["snapshot"]
            raw_bytes = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "invalid order-book action"):
                verify_capture(summary)

    def test_rejects_non_string_evidence_verdict_without_type_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            data = json.loads(summary.read_text())
            data["continuity_evidence_verdict"] = ["VERIFIED_24H"]
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "Unknown continuity evidence verdict"):
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
            with self.assertRaisesRegex(CaptureVerificationError, "rejected_frames_count conflicts"):
                verify_capture(summary)


    def test_rejects_duplicate_keys_in_summary_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            content = summary.read_text(encoding="utf-8")
            content = content.replace(
                '"raw_capture_file": "raw.jsonl",',
                '"raw_capture_file": "raw.jsonl", "raw_capture_file": "raw.jsonl",',
                1,
            )
            summary.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "Duplicate JSON object key: raw_capture_file"):
                verify_capture(summary)

    def test_rejects_duplicate_nested_keys_in_raw_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            content = raw.read_text(encoding="utf-8")
            content = content.replace('"seq": 1', '"seq": 1, "seq": 1', 1)
            raw_bytes = content.encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "JSONL record 1 is invalid: Duplicate JSON object key: seq"):
                verify_capture(summary)


    def test_rejects_nan_in_summary_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            content = summary.read_text(encoding="utf-8")
            content = content.replace('"duration_seconds": 86400', '"duration_seconds": NaN', 1)
            summary.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "Non-finite JSON numeric constant: NaN"):
                verify_capture(summary)

    def test_rejects_infinity_in_raw_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            content = raw.read_text(encoding="utf-8")
            content = content.replace('"seq": 1', '"seq": 1, "extra_numeric": Infinity', 1)
            raw_bytes = content.encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "JSONL record 1 is invalid: Non-finite JSON numeric constant: Infinity"):
                verify_capture(summary)

    def test_rejects_overflowing_json_float_in_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            content = summary.read_text(encoding="utf-8")
            content = content.replace('"duration_seconds": 86400', '"duration_seconds": 1e999', 1)
            summary.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "Non-finite JSON numeric value: 1e999"):
                verify_capture(summary)


    def _rewrite_raw_record(self, root: Path, summary: Path, mutate) -> None:
        raw = root / "raw.jsonl"
        record = json.loads(raw.read_text(encoding="utf-8"))
        mutate(record)
        raw_bytes = (json.dumps(record, sort_keys=True) + "\\n").encode("utf-8")
        raw.write_bytes(raw_bytes)
        data = json.loads(summary.read_text(encoding="utf-8"))
        data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        data["total_bytes_written"] = len(raw_bytes)
        summary.write_text(json.dumps(data), encoding="utf-8")

    def test_rejects_accepted_book_level_with_invalid_decimal_price(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            self._rewrite_raw_record(root, summary, lambda record: record["raw"].update(b=[["not-a-price", "1"]]))
            with self.assertRaisesRegex(CaptureVerificationError, "has invalid price"):
                verify_capture(summary)

    def test_rejects_accepted_book_level_with_zero_price(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            self._rewrite_raw_record(root, summary, lambda record: record["raw"].update(b=[["0", "1"]]))
            with self.assertRaisesRegex(CaptureVerificationError, "price must be finite and positive"):
                verify_capture(summary)

    def test_rejects_accepted_book_level_with_negative_size(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            self._rewrite_raw_record(root, summary, lambda record: record["raw"].update(a=[["101", "-0.1"]]))
            with self.assertRaisesRegex(CaptureVerificationError, "size must be finite and positive"):
                verify_capture(summary)

    def test_rejects_accepted_book_level_with_malformed_pair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            self._rewrite_raw_record(root, summary, lambda record: record["raw"].update(b=[["99"]]))
            with self.assertRaisesRegex(CaptureVerificationError, "must be a price/size pair"):
                verify_capture(summary)

    def test_preserves_malformed_levels_on_tracker_rejected_frames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root, accepted=False)
            self._rewrite_raw_record(root, summary, lambda record: record["raw"].update(b=[["malformed"]]))
            result = verify_capture(summary)
            self.assertTrue(result["integrity_valid"])
            self.assertFalse(result["evidence_eligible"])
            self.assertEqual(result["persisted_tracker_rejections"], 1)


    def test_rejects_excessive_summary_json_nesting_without_recursion_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            content = summary.read_text(encoding="utf-8").rstrip()
            summary.write_text(content[:-1] + ', "deep": ' + ("[" * 1500) + "0" + ("]" * 1500) + "}", encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "Summary JSON nesting exceeds verifier limit"):
                verify_capture(summary)

    def test_rejects_excessive_raw_jsonl_nesting_without_recursion_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            line = raw.read_text(encoding="utf-8").rstrip()
            raw_bytes = (line[:-1] + ', "deep": ' + ("[" * 1500) + "0" + ("]" * 1500) + "}\\n").encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "JSONL record 1 exceeds verifier nesting limit"):
                verify_capture(summary)


    def test_rejects_verification_cpu_budget_exhaustion(self):
        with tempfile.TemporaryDirectory() as td:
            summary = self._write_fixture(Path(td))
            with patch("scripts.verify_l2_capture_artifacts.time.process_time", side_effect=[0.0, 901.0]):
                with self.assertRaisesRegex(CaptureVerificationError, "Artifact verification exceeded CPU-time budget"):
                    verify_capture(summary)

    def test_accepts_verification_within_cpu_budget(self):
        with tempfile.TemporaryDirectory() as td:
            summary = self._write_fixture(Path(td))
            with patch("scripts.verify_l2_capture_artifacts.time.process_time", return_value=0.0):
                self.assertTrue(verify_capture(summary)["integrity_valid"])

    def test_rejects_summary_with_oversized_json_array(self):
        with tempfile.TemporaryDirectory() as td:
            summary = self._write_fixture(Path(td))
            data = json.loads(summary.read_text())
            data["attacker_controlled"] = list(range(8193))
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "JSON array item limit"):
                verify_capture(summary)

    def test_rejects_raw_record_with_oversized_json_object(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            record = json.loads(raw.read_text())
            record["attacker_controlled"] = {str(i): i for i in range(8193)}
            raw_bytes = (json.dumps(record, sort_keys=True) + "\\n").encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text())
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "JSON object member limit"):
                verify_capture(summary)

    def test_rejects_json_with_excessive_aggregate_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            summary = self._write_fixture(Path(td))
            data = json.loads(summary.read_text())
            data["attacker_controlled"] = [list(range(13)) for _ in range(8192)]
            summary.write_text(json.dumps(data))
            with self.assertRaisesRegex(CaptureVerificationError, "JSON node limit"):
                verify_capture(summary)

    def test_rejects_oversized_summary(self):
        with tempfile.TemporaryDirectory() as td:
            summary = self._write_fixture(Path(td))
            with patch("scripts.verify_l2_capture_artifacts._MAX_SUMMARY_BYTES", summary.stat().st_size - 1):
                with self.assertRaisesRegex(CaptureVerificationError, "Summary JSON exceeds verifier byte limit"):
                    verify_capture(summary)

    def test_rejects_oversized_raw_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            with patch("scripts.verify_l2_capture_artifacts._MAX_JSONL_RECORD_BYTES", 16):
                with self.assertRaisesRegex(CaptureVerificationError, "JSONL record 1 exceeds verifier byte limit"):
                    verify_capture(summary)

    def test_rejects_total_raw_capture_byte_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw_size = (root / "raw.jsonl").stat().st_size
            with patch("scripts.verify_l2_capture_artifacts._MAX_RAW_CAPTURE_BYTES", raw_size - 1):
                with self.assertRaisesRegex(CaptureVerificationError, "Raw capture exceeds verifier total byte limit"):
                    verify_capture(summary)

    def test_rejects_raw_capture_frame_count_limit(self):
        with tempfile.TemporaryDirectory() as td:
            summary = self._write_fixture(Path(td))
            with patch("scripts.verify_l2_capture_artifacts._MAX_RAW_CAPTURE_FRAMES", 0):
                with self.assertRaisesRegex(CaptureVerificationError, "Raw capture exceeds verifier frame-count limit"):
                    verify_capture(summary)

    def test_accepts_exact_resource_limits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw_size = (root / "raw.jsonl").stat().st_size
            with patch("scripts.verify_l2_capture_artifacts._MAX_SUMMARY_BYTES", summary.stat().st_size), patch("scripts.verify_l2_capture_artifacts._MAX_JSONL_RECORD_BYTES", raw_size), patch("scripts.verify_l2_capture_artifacts._MAX_RAW_CAPTURE_BYTES", raw_size), patch("scripts.verify_l2_capture_artifacts._MAX_RAW_CAPTURE_FRAMES", 1):
                self.assertTrue(verify_capture(summary)["integrity_valid"])


    def test_rejects_oversized_json_integer_token(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            content = raw.read_text(encoding="utf-8").replace('"seq": 1', '"seq": ' + ('9' * 129), 1)
            raw_bytes = content.encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "JSON integer exceeds verifier digit limit"):
                verify_capture(summary)

    def test_rejects_oversized_json_string(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            record = json.loads(raw.read_text(encoding="utf-8"))
            record["raw"]["sy"] = "X" * 65_537
            raw_bytes = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "JSON string length limit"):
                verify_capture(summary)

    def test_rejects_excessive_decimal_exponent_in_accepted_book_level(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            self._rewrite_raw_record(root, summary, lambda record: record["raw"].update(b=[["1e1001", "1"]]))
            with self.assertRaisesRegex(CaptureVerificationError, "price must be finite and positive"):
                verify_capture(summary)



    def test_rejects_summary_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = self._write_fixture(root)
            link = root / "summary-link.json"
            try:
                link.symlink_to(original)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(CaptureVerificationError, "Summary must be a regular, non-symlink file"):
                verify_capture(link)

    def test_rejects_raw_capture_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            outside = root / "outside.jsonl"
            raw.rename(outside)
            try:
                raw.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(CaptureVerificationError, "Raw capture must be a regular, non-symlink file"):
                verify_capture(summary)

    def test_rejects_oversized_integer_token_in_raw_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = self._write_fixture(root)
            raw = root / "raw.jsonl"
            content = raw.read_text(encoding="utf-8").replace('"seq": 1', '"seq": ' + ('9' * 129), 1)
            raw_bytes = content.encode("utf-8")
            raw.write_bytes(raw_bytes)
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["raw_capture_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
            data["total_bytes_written"] = len(raw_bytes)
            summary.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CaptureVerificationError, "JSONL record 1 is invalid: JSON integer exceeds verifier digit limit"):
                verify_capture(summary)



if __name__ == "__main__":
    unittest.main()
