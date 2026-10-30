# Phase 234 — Verify archive payloads against the manifest

Phase 233 hardened the detached release-record parser. Phase 234 closes a
separate verification gap: archive member coverage alone does not prove that
member bytes match the hashes declared by `BUILD_MANIFEST.sha256`.

The release-candidate verifier now parses each manifest entry strictly,
rejects malformed hashes, duplicate paths, absolute/traversal/backslash paths,
and self-hashing entries, and computes SHA-256 over every archived payload.
The archive is rejected if any member differs from its manifest digest. This
check runs on the exact candidate before and after copying, and the workflow's
Ubuntu/Windows release matrix includes the new regression tests and names its
artifacts `PHASE234`.

This local implementation and test coverage do not establish that hosted CI
has run. Hosted Ubuntu/Windows results still need inspection in the connected
repository. The complete test suite remains uncertified; this is not a
production or live-trading approval.
