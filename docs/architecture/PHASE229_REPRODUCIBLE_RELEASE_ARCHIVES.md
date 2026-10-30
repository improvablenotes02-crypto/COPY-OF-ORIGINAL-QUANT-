# Phase 229 — Reproducible release archives

## Change

The release builder now normalizes ZIP member timestamps and file mode bits,
uses a fixed compression level, and writes bytes in sorted path order. This
removes source mtimes and platform-specific permission metadata as causes of
release-hash drift. The detached archive SHA-256 remains outside the archive.

## Regression coverage

- Two builds of the same source tree must have identical SHA-256 values even
  when a source file's mtime changes between builds.
- ZIP member ordering, normalized timestamps, manifest bytes, and archive
  integrity must agree between builds.
- `.env` and `.git` content must remain excluded while `.env.example` is kept.
- Changing actual source content must change the archive hash.

## Evidence boundary

This verifies deterministic packaging for the covered fixture and the build
script's normalized metadata contract. It does not certify the full repository
test suite, native Windows process cleanup, trading performance, broker
connectivity, or live-trading safety. Live orders remain disabled/on hold.
