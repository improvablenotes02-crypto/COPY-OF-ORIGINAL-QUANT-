# Phase 233 — Strict detached release-record fields

The detached release record is now parsed as a strict, versioned-by-header
contract rather than a best-effort collection of key/value lines. Verification
rejects an invalid header, malformed lines, duplicate keys, missing required
fields, and unexpected fields before comparing the artifact's filename, SHA-256,
byte count, archive member count, and PASS assertions. This prevents a duplicate
line later in the record from silently overriding a previous value.

The Ubuntu and Windows release-candidate matrix now names its outputs and uploaded
artifacts `PHASE233`. This workflow definition is not proof of hosted execution;
actual GitHub Actions results and platform artifacts must still be inspected in
the repository where the workflow is installed. The full test suite has not been
certified, and live trading remains disabled/on hold.
