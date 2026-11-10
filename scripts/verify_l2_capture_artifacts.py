"""Independently verify the byte integrity and evidence claims of an L2 capture.

This verifier is offline and read-only. It never connects to an exchange or writes
orders. Integrity success does not itself establish a VERIFIED_24H evidence verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
    previous_receipt_mono_ns = 0
    symbol_counts: dict[str, dict[str, int]] = {}
    accepted_sequences: dict[str, int] = {}
    with raw_path.open("rb") as stream:
        for number, line in enumerate(stream, start=1):
            digest.update(line)
            byte_count += len(line)
            if not line.endswith(b"\n"):
                raise CaptureVerificationError(f"JSONL record {number} is not LF terminated")
            try:
                record = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise CaptureVerificationError(f"JSONL record {number} is invalid: {exc}") from exc
            if not isinstance(record, dict):
                raise CaptureVerificationError(f"JSONL record {number} must be an object")
            if type(record.get("receipt_mono_ns")) is not int or record["receipt_mono_ns"] <= 0:
                raise CaptureVerificationError(f"JSONL record {number} has invalid monotonic receipt time")
            receipt_mono_ns = record["receipt_mono_ns"]
            if receipt_mono_ns < previous_receipt_mono_ns:
                raise CaptureVerificationError(f"JSONL record {number} has regressing monotonic receipt time")
            previous_receipt_mono_ns = receipt_mono_ns
            if type(record.get("receipt_utc_ns")) is not int or record["receipt_utc_ns"] <= 0:
                raise CaptureVerificationError(f"JSONL record {number} has invalid UTC receipt time")
            raw = record.get("raw")
            if not isinstance(raw, dict) or raw.get("type") != "ob_updates":
                raise CaptureVerificationError(f"JSONL record {number} is not an order-book update")
            symbol = raw.get("sy")
            sequence = raw.get("seq")
            venue_timestamp_us = raw.get("ts")
            if not isinstance(symbol, str) or not symbol or symbol != symbol.strip():
                raise CaptureVerificationError(f"JSONL record {number} has invalid symbol")
            if type(sequence) is not int or sequence <= 0:
                raise CaptureVerificationError(f"JSONL record {number} has invalid sequence")
            if type(venue_timestamp_us) is not int or venue_timestamp_us <= 0:
                raise CaptureVerificationError(f"JSONL record {number} has invalid venue timestamp")
            action = raw.get("action", "update")
            if action not in {"snapshot", "update"}:
                raise CaptureVerificationError(f"JSONL record {number} has invalid order-book action")
            if type(record.get("tracker_accepted")) is not bool:
                raise CaptureVerificationError(f"JSONL record {number} lacks tracker_accepted boolean")
            counts = symbol_counts.setdefault(symbol, {"frames": 0, "accepted": 0, "rejected": 0})
            counts["frames"] += 1
            if record["tracker_accepted"]:
                previous_sequence = accepted_sequences.get(symbol)
                if action == "snapshot":
                    accepted_sequences[symbol] = sequence
                else:
                    if previous_sequence is None:
                        raise CaptureVerificationError(f"JSONL record {number} has accepted update before an accepted snapshot")
                    if sequence != previous_sequence + 1:
                        raise CaptureVerificationError(f"JSONL record {number} has accepted sequence gap, duplicate, or regression")
                    accepted_sequences[symbol] = sequence
                counts["accepted"] += 1
            else:
                rejected_persisted += 1
                counts["rejected"] += 1
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

    symbol_quality = summary.get("symbol_quality")
    if not isinstance(symbol_quality, dict):
        raise CaptureVerificationError("symbol_quality must be a per-symbol metrics map")
    for symbol, counts in symbol_counts.items():
        metrics = symbol_quality.get(symbol)
        if not isinstance(metrics, dict):
            raise CaptureVerificationError(f"Raw symbol {symbol} is missing from symbol_quality")
        if type(metrics.get("total_messages")) is not int or metrics["total_messages"] != counts["frames"]:
            raise CaptureVerificationError(f"Per-symbol total_messages mismatch for {symbol}")
        if type(metrics.get("valid_updates")) is not int or metrics["valid_updates"] != counts["accepted"]:
            raise CaptureVerificationError(f"Per-symbol valid_updates mismatch for {symbol}")
        if type(metrics.get("rejected_count")) is not int or metrics["rejected_count"] != counts["rejected"]:
            raise CaptureVerificationError(f"Per-symbol rejected_count mismatch for {symbol}")
    for symbol, metrics in symbol_quality.items():
        if not isinstance(symbol, str) or not isinstance(metrics, dict):
            raise CaptureVerificationError("symbol_quality contains an invalid entry")
        if symbol not in symbol_counts and any(
            type(metrics.get(key)) is not int or metrics[key] != 0
            for key in ("total_messages", "valid_updates", "rejected_count")
        ):
            raise CaptureVerificationError(f"Per-symbol metrics claim unobserved frames for {symbol}")

    checks = summary.get("continuity_checks")
    if not isinstance(checks, dict) or not checks or any(type(value) is not bool for value in checks.values()):
        raise CaptureVerificationError("continuity_checks must be a non-empty boolean map")
    verdict = summary.get("continuity_evidence_verdict")
    if verdict not in {"PARTIAL", "VERIFIED_24H"}:
        raise CaptureVerificationError("Unknown continuity evidence verdict")
    duration = summary.get("duration_seconds")
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
        raise CaptureVerificationError("duration_seconds is missing or invalid")
    if verdict == "VERIFIED_24H" and (
        not all(checks.values())
        or rejected_persisted
        or rejected_count != 0
        or checks.get("minimum_24h_duration") is not True
        or duration < 86400.0
    ):
        raise CaptureVerificationError("VERIFIED_24H conflicts with failed checks, rejected frames, or short duration")

    return {
        "integrity_valid": True,
        "evidence_verdict": verdict,
        "evidence_eligible": verdict == "VERIFIED_24H",
        "raw_capture_file": raw_name,
        "raw_capture_sha256": actual_hash,
        "raw_capture_bytes": byte_count,
        "raw_capture_frames": frame_count,
        "persisted_tracker_rejections": rejected_persisted,
        "symbols_verified": len(symbol_counts),
        "per_symbol_frame_counts": {symbol: counts["frames"] for symbol, counts in sorted(symbol_counts.items())},
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
