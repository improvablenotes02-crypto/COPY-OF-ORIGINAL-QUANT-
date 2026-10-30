# Phase 231 — Exact CI release candidate verification

## Change

The cross-platform release job now builds the release archive twice outside the
source tree, compares SHA-256 hashes, validates ZIP CRCs and unique member names,
checks manifest-to-archive coverage, rejects secret-like archive members, copies
the verified bytes to the requested candidate path, and re-verifies that copied
artifact. It writes a detached SHA-256 record and uploads that exact archive and
record as a GitHub Actions artifact on each runner.

## Evidence boundary

The workflow configuration and local tests establish the checks implemented by
the workflow; they do not establish that a hosted Windows or Ubuntu workflow has
actually completed successfully. A successful run and downloaded artifact hash
must be observed separately. This is not a signed release, does not attest to
source provenance beyond the checkout used by CI, and does not establish trading
safety or profitability.

Live trading remains on hold.
