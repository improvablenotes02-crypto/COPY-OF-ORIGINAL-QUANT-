"""Independently verify the byte integrity and evidence claims of an L2 capture.

This verifier is offline and read-only. It never connects to an exchange or writes
orders. Integrity success does not itself establish a VERIFIED_24H evidence verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_HEX64 = re.compile(r"[0-9a-f]{64}")


class CaptureVerificationError(ValueError):
    """Raised when a capture artifact is missing, unsafe, or inconsistent."""


def verify_capture(summary_path: Path) -> dict[str, Any]:
    summary_path = Path(summary_path)
    if summary_path.is_symlink() or not summary_path.is_file():
        raise CaptureVerificationError("Summary must be a regular, non-symlink file")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureVerificationError(f"Cannot read summary JSON: {exc}") from exc
    if not isinstance(summary, dict):
        raise CaptureVerificationError("Summary root must be a JSON object")

    raw_name = summary.get("raw_capture_file")
    if not isinstance(raw_name, str) or not raw_name or Path(raw_name).name != raw_name:
        raise CaptureVerificationError("raw_capture_file must be a basename within the summary directory")
    raw_path = summary_path.parent / raw_name
    if raw_path.is_symlink() or not raw_path.is_file():
        raise CaptureVerificationError("Raw capture must be a regular, non-symlink file")

    expected_hash = summary.get("raw_capture_sha256")
    if not isinstance(expected_hash, str) or not _HEX64.fullmatch(expected_hash):
        raise CaptureVerificationError("Summary raw_capture_sha256 is missing or malformed")
    digest = hashlib.sha256()
    byte_count = 0
    frame_count = 0
    rejected_persisted = 0
    with raw_path.open("rb") as stream:
        for number, line in enumerate(stream, start=1):
            digest.update(line)
            byte_count += len(line)
            if not line.endswith(b"\\n"):
                raise CaptureVerificationError(f"JSONL record {number} is not LF terminated")
            try:
                record = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise CaptureVerificationError(f"JSONL record {number} is invalid: {exc}") from exc
            if not isinstance(record, dict):
                raise CaptureVerificationError(f"JSONL record {number} must be an object")
            if type(record.get("receipt_mono_ns")) is not int or record["receipt_mono_ns"] <= 0:
                raise CaptureVerificationError(f"JSONL record {number} has invalid monotonic receipt time")
            if type(record.get("receipt_utc_ns")) is not int or record["receipt_utc_ns"] <= 0:
                raise CaptureVerificationError(f"JSONL record {number} has invalid UTC receipt time")
            if not isinstance(record.get("raw"), dict) or record["raw"].get("type") != "ob_updates":
                raise CaptureVerificationError(f"JSONL record {number} is not an order-book update")
            if type(record.get("tracker_accepted")) is not bool:
                raise CaptureVerificationError(f"JSONL record {number} lacks tracker_accepted boolean")
            if not record["tracker_accepted"]:
                rejected_persisted += 1
            frame_count += 1
    actual_hash = digest.hexdigest()
    if actual_hash != expected_hash:
        raise CaptureVerificationError("Raw capture SHA-256 does not match summary")

    expected_size = summary.get("total_bytes_written")
    if type(expected_size) is not int or expected_size < 0 or expected_size != byte_count:
        raise CaptureVerificationError("Raw capture byte count does not match summary")

    expected_frames = summary.get("total_raw_frames")
    if type(expected_frames) is not int or expected_frames < 0 or expected_frames != frame_count:
        raise CaptureVerificationError("Raw frame count does not match summary")
    rejected_count = summary.get("rejected_frames_count")
    if type(rejected_count) is not int or rejected_count < rejected_persisted:
        raise CaptureVerificationError("Persisted rejected frames exceed summary rejected count")

    checks = summary.get("continuity_checks")
    if not isinstance(checks, dict) or not checks or any(type(value) is not bool for value in checks.values()):
        raise CaptureVerificationError("continuity_checks must be a non-empty boolean map")
    verdict = summary.get("continuity_evidence_verdict")
    if verdict not in {"PARTIAL", "VERIFIED_24H"}:
        raise CaptureVerificationError("Unknown continuity evidence verdict")
    if verdict == "VERIFIED_24H" and (not all(checks.values()) or rejected_persisted):
        raise CaptureVerificationError("VERIFIED_24H conflicts with failed checks or rejected persisted frames")

    return {
        "integrity_valid": True,
        "evidence_verdict": verdict,
        "evidence_eligible": verdict == "VERIFIED_24H",
        "raw_capture_file": raw_name,
        "raw_capture_sha256": actual_hash,
        "raw_capture_bytes": byte_count,
        "raw_capture_frames": frame_count,
        "persisted_tracker_rejections": rejected_persisted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a QuantEngine L2 capture summary and raw JSONL artifact")
    parser.add_argument("--summary", required=True, type=Path, help="Path to the capture summary JSON")
    args = parser.parse_args()
    try:
        result = verify_capture(args.summary)
    except (CaptureVerificationError, OSError) as exc:
        print(json.dumps({"integrity_valid": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
