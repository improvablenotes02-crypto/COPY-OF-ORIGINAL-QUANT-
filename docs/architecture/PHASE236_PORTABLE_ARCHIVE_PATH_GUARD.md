# Phase 236 — Portable archive path validation

## Change

The release-candidate verifier now rejects manifest paths that are unsafe across
supported extraction platforms: Windows drive-qualified paths (for example,
`C:/...`) and ASCII control characters, in addition to the existing checks for
absolute paths, backslashes, empty components, `.` and `..` components.

## Why

A ZIP assembled on a POSIX host can be consumed on Windows. Validation must
therefore not rely solely on the host platform's interpretation of paths.

## Verification

The focused archive-manifest regression suite includes explicit negative cases
for Windows drive-qualified and control-character paths. Release packaging also
continues to verify exact manifest coverage and every payload SHA-256.

## Safety posture

This is a packaging-integrity improvement only. It does not establish strategy
profitability, exchange connectivity readiness, production readiness, or
permission to submit live orders. Live trading remains on HOLD.
