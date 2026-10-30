# Phase 237 — Windows Extraction Collision Guard

## Problem

A release archive produced on POSIX can be extracted on Windows. Windows filename
semantics introduce collisions and alternate interpretations that POSIX permits:
case-insensitive names can overwrite one another, DOS device basenames are reserved,
NTFS colons can select alternate data streams, and trailing dots/spaces are normalized.

## Change

The release-candidate verifier now rejects manifest paths containing Windows-invalid
filename characters, reserved DOS device basenames (including COM1–COM9 and
LPT1–LPT9), trailing dots/spaces, and case-fold collisions. Existing checks for
absolute paths, traversal, drive prefixes, backslashes, and control characters remain.

## Evidence

`tests/test_phase237_windows_portable_paths.py` adds offline ZIP fixtures for reserved
device names, NTFS alternate data streams, trailing-dot/space names, and
case-insensitive collisions. These checks validate package safety only; they do not
constitute hosted Windows extraction/CI evidence.

## Limitations

Unicode normalization and every filesystem-specific edge case are not proven by this
guard. Hosted Windows CI and a real extraction test remain outstanding. No exchange
writes are enabled by this change.
