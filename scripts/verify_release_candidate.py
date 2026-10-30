"""Build, verify and emit a detached record for the exact CI release candidate.

This script intentionally builds twice outside the source tree, compares the
archive bytes, validates ZIP integrity and secret exclusions, then copies the
verified first archive to the requested destination. It does not publish a
GitHub Release or enable trading.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SECRET_EXACT = {".env", ".env.local", ".env.test", ".env.prod", "credentials"}
SECRET_SUFFIXES = {".pem", ".key", ".secret", ".secrets", ".p12", ".pfx", ".keystore"}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prohibited_member(name: str) -> bool:
    path = Path(name)
    base = path.name.lower()
    if base.startswith(".env") and base != ".env.example":
        return True
    if base in SECRET_EXACT or path.suffix.lower() in SECRET_SUFFIXES:
        return True
    if "credentials" in base and path.suffix.lower() in {".json", ".txt"}:
        return True
    return False


def verify_archive(path: Path) -> tuple[int, list[str]]:
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        if len(members) != len(set(members)):
            raise RuntimeError("archive contains duplicate member names")
        damaged = archive.testzip()
        if damaged:
            raise RuntimeError("ZIP CRC failure: " + damaged)
        bad = [name for name in members if prohibited_member(name)]
        if bad:
            raise RuntimeError("prohibited secret-like members: " + ", ".join(bad))
        if "BUILD_MANIFEST.sha256" not in members:
            raise RuntimeError("archive is missing BUILD_MANIFEST.sha256")
        try:
            manifest = archive.read("BUILD_MANIFEST.sha256").decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("manifest is not valid UTF-8") from exc
        manifest_hashes: dict[str, str] = {}
        portable_names: dict[str, str] = {}
        for line_number, line in enumerate(manifest.splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) != 2 or not _HEX64.fullmatch(parts[0]):
                raise RuntimeError(f"malformed manifest line {line_number}")
            digest, name = parts
            name = name.strip()
            # ZIP member names are POSIX paths regardless of host platform.
            # Treat archive paths as portable POSIX paths, but also reject
            # Windows drive-qualified paths and control characters. A ZIP
            # created on Linux may still be extracted on Windows.
            drive_qualified = bool(re.match(r"^[A-Za-z]:", name))
            has_control = any(ord(char) < 32 or ord(char) == 127 for char in name)
            parts = name.split("/")
            # Windows extraction adds hazards beyond traversal: NTFS alternate
            # data streams, reserved DOS device basenames, invalid filename
            # characters, and names normalized by trimming dots or spaces.
            reserved_devices = {"CON", "PRN", "AUX", "NUL"}
            reserved_devices.update(f"COM{i}" for i in range(1, 10))
            reserved_devices.update(f"LPT{i}" for i in range(1, 10))
            windows_invalid = any(
                any(char in '<>:\"|?*' for char in part)
                or part.endswith((".", " "))
                or part.split(".", 1)[0].upper() in reserved_devices
                # Win32 also reserves the superscript 1/2/3 spellings.
                or part.split(".", 1)[0].upper() in {
                    "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"
                }
                # Keep each component within the common Win32/NTFS limit.
                or len(part.encode("utf-16-le")) // 2 > 255
                for part in parts
            )
            if (not name or name.startswith("/") or drive_qualified
                    or has_control or "\\" in name or windows_invalid
                    or any(part in {"", ".", ".."} for part in parts)):
                raise RuntimeError(f"unsafe manifest path on line {line_number}: {name!r}")
            if name == "BUILD_MANIFEST.sha256":
                raise RuntimeError("manifest must not contain its own hash")
            if name in manifest_hashes:
                raise RuntimeError(f"duplicate manifest path: {name}")
            portable_key = name.casefold()
            if portable_key in portable_names:
                raise RuntimeError(
                    "case-insensitive manifest path collision: "
                    f"{portable_names[portable_key]!r} and {name!r}"
                )
            portable_names[portable_key] = name
            manifest_hashes[name] = digest
        manifest_paths = set(manifest_hashes)
        expected = manifest_paths | {"BUILD_MANIFEST.sha256"}
        actual = set(members)
        if actual != expected:
            raise RuntimeError(
                "archive/manifest coverage mismatch: "
                f"missing={sorted(expected - actual)[:10]}, extra={sorted(actual - expected)[:10]}"
            )
        for name, expected_digest in manifest_hashes.items():
            actual_digest = hashlib.sha256(archive.read(name)).hexdigest()
            if actual_digest != expected_digest:
                raise RuntimeError(f"manifest hash mismatch: {name}")
        return len(members), members


def build_candidate(root: Path, output: Path) -> dict:
    root = root.resolve()
    output = output.resolve()
    builder = root / "scripts" / "build_release.py"
    if not builder.is_file():
        raise RuntimeError(f"release builder not found: {builder}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qe-phase231-") as temp:
        temp_root = Path(temp)
        first, second = temp_root / "candidate-a.zip", temp_root / "candidate-b.zip"
        for target in (first, second):
            subprocess.run(
                [sys.executable, str(builder), "--root", str(root), "--output", str(target)],
                check=True, capture_output=True, text=True, timeout=180,
            )
        first_hash, second_hash = sha256(first), sha256(second)
        if first_hash != second_hash:
            raise RuntimeError(f"reproducibility failure: {first_hash} != {second_hash}")
        members, _ = verify_archive(first)
        shutil.copyfile(first, output)
    # Verify the exact copied artifact, not only the temporary build.
    copied_members, _ = verify_archive(output)
    final_hash = sha256(output)
    if final_hash != first_hash or copied_members != members:
        raise RuntimeError("copied candidate differs from verified build")
    record = output.with_suffix(output.suffix + ".sha256.txt")
    record.write_text(
        "QuantEngine CI release candidate verification\n"
        f"Artifact: {output.name}\nSHA-256: {final_hash}\n"
        f"Bytes: {output.stat().st_size}\nArchive members: {copied_members}\n"
        "Reproducible second build: PASS\nZIP integrity: PASS\n"
        "Manifest coverage: PASS\nManifest payload digests: PASS\nSecret-file exclusion: PASS\n",
        encoding="utf-8", newline="\n",
    )
    return {"artifact": str(output), "sha256": final_hash,
            "bytes": output.stat().st_size, "members": copied_members,
            "record": str(record)}


def verify_detached_record(artifact: Path, record: Path) -> dict:
    """Verify a detached record against the exact artifact bytes on disk."""
    artifact = artifact.resolve()
    record = record.resolve()
    if not artifact.is_file():
        raise RuntimeError(f"artifact not found: {artifact}")
    if not record.is_file():
        raise RuntimeError(f"detached record not found: {record}")
    lines = record.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "QuantEngine CI release candidate verification":
        raise RuntimeError("detached record header is missing or invalid")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        if ": " not in line:
            raise RuntimeError(f"malformed detached-record line: {line!r}")
        key, value = line.split(": ", 1)
        if key in fields:
            raise RuntimeError(f"duplicate detached-record field: {key}")
        fields[key] = value
    required = {"Artifact", "SHA-256", "Bytes", "Archive members",
                "Reproducible second build", "ZIP integrity",
                "Manifest coverage", "Manifest payload digests", "Secret-file exclusion"}
    missing = required - fields.keys()
    unexpected = fields.keys() - required
    if missing or unexpected:
        raise RuntimeError(
            f"detached record field mismatch: missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    expected_name = fields["Artifact"]
    actual_hash = sha256(artifact)
    actual_bytes = artifact.stat().st_size
    if expected_name != artifact.name:
        raise RuntimeError(f"artifact name mismatch: record={expected_name!r}, actual={artifact.name!r}")
    if fields.get("SHA-256") != actual_hash:
        raise RuntimeError("detached SHA-256 does not match artifact")
    if fields.get("Bytes") != str(actual_bytes):
        raise RuntimeError("detached byte count does not match artifact")
    member_count, _ = verify_archive(artifact)
    if fields.get("Archive members") != str(member_count):
        raise RuntimeError("detached archive member count does not match artifact")
    for label in ("Reproducible second build", "ZIP integrity",
                  "Manifest coverage", "Manifest payload digests", "Secret-file exclusion"):
        if fields.get(label) != "PASS":
            raise RuntimeError(f"detached record missing PASS for {label}")
    return {"artifact": str(artifact), "sha256": actual_hash,
            "bytes": actual_bytes, "members": member_count, "record": str(record),
            "detached_record": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-record", type=Path, help="verify this artifact against --record")
    parser.add_argument("--record", type=Path, help="detached record path used with --verify-record")
    args = parser.parse_args()
    try:
        if args.verify_record is not None:
            if args.output is not None or args.record is None:
                parser.error("--verify-record requires --record and cannot be combined with --output")
            result = verify_detached_record(args.verify_record, args.record)
        else:
            if args.output is None:
                parser.error("--output is required unless --verify-record is used")
            if args.record is not None:
                parser.error("--record is only valid with --verify-record")
            result = build_candidate(args.root, args.output)
    except Exception as exc:
        print(f"release candidate verification FAILED: {exc}", file=sys.stderr)
        return 1
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
