# Phases 401-404 — identity-bound backup verification and process safety
- **401:** Extend semantic queue integrity checks to the persisted principal snapshot: non-empty tenant/subject/session, canonical tenant list containing the row tenant, finite principal expiry and job expiry no later than principal expiry.
- **402:** Allow backup verification to bind an expected state-count mapping, rejecting malformed mappings and mismatched snapshots.
- **403:** Add a spawned independent-process race test proving only one process can publish a shared backup destination; the other receives no-clobber collision.
- **404:** Inject backup validation failure and assert temporary artifacts are removed and no destination is published.
No queue transitions, automatic replay, exactly-once claim, or live authorization are introduced. SQLite remains local single-host maintenance and production readiness remains false.
- **405:** Validate each job's principal snapshot from the same row, eliminating ambiguous timestamp-based identity lookups when jobs share timestamps.
- **406:** Validate all numeric timestamps and principal expiry before comparisons; malformed SQLite values fail closed without leaking a type error.
- **407:** Bind restore drills to expected queue-state counts at source verification and after isolated restore.
- **408:** Inject post-restore count-verification failure and assert no restore destination or private temporary artifact is left behind.

- **409:** Backup digests must be hexadecimal SHA-256 values; verification opens the SQLite artifact read-only and cannot write through the verification connection.
- **410:** Keep backup verification non-mutating by enforcing SQLite query-only mode and read-only URI access.
- **411:** Add a bounded owner-only inventory report with verified, rejected, candidate and truncation counts; retain the tuple API as a compatibility wrapper.
- **412:** Extend the maintenance health summary with bounded inventory metrics while preserving explicit replay-disabled and production-not-ready indicators.

- **413:** Replace full directory materialization with incremental scandir; cap every directory entry inspected and reject symlinks/non-regular files without following them.
- **414:** Add a positive total-byte verification budget; oversized candidates are rejected and the report marks the scan truncated rather than spending unbounded I/O.
- **415:** Compare no-follow file identity, size and modification time before and after verification; reject candidates that change during the scan. This narrows, but does not eliminate, filesystem TOCTOU risk.
- **416:** Make maintenance health explicitly degraded when inventory cannot be read; report a sanitized error flag and never disguise the failure as a healthy empty inventory.

- **417:** Normalize Windows drive paths into SQLite read-only file URIs while preserving mode=ro and query-only verification.
- **418:** Add sanitized per-category rejection counts so operators can distinguish malformed backups, filesystem errors and non-regular entries without exposing paths or exception text.
- **419:** Exclude hard-link aliases of the live queue database from backup inventory; a live mutable database is not accepted as a backup artifact.
- **420:** Validate the inventory root using a no-follow filesystem stat and reject symlinked directory roots.

- **421:** Build SQLite read-only backup URIs with pathlib's platform-aware URI encoder; retain explicit mode=ro and query-only enforcement on Windows and POSIX.
- **422:** Recheck file identity, size, modification time and SHA-256 after SQLite inspection; reject artifacts changed during verification.
- **423:** Recheck inventory directory identity after scanning; fail closed if the root directory was replaced during the scan.
- **424:** Normalize inventory rejection diagnostics to allow-listed categories; never expose exception messages or filesystem paths in health output.

- **425:** Use a guarded Windows SQLite URI fallback for drive-letter paths while preserving read-only mode; verify paths containing spaces and URI-reserved characters.
- **426:** Certify that symlink backup paths cannot pass direct verification, not only inventory filtering.
- **427:** Prove the total-byte budget is applied before hashing candidate contents, bounding I/O as well as SQLite verification.
- **428:** Verify maintenance health sanitizes inventory permission failures and keeps replay disabled and production readiness false.

- **429:** Prefer the Windows drive-letter SQLite read-only URI before the canonical URI to avoid a successful open of the wrong database on affected SQLite builds; certify paths containing spaces and URI-reserved characters.
- **430:** Reject direct backup verification of hard-link aliases to the live queue database, closing the gap between inventory filtering and the public verification boundary.
- **431:** Prove a digest mismatch is rejected before SQLite is opened, avoiding unnecessary parsing of untrusted backup contents.
- **432:** Verify inventory and health summaries never expose low-level SQLite exception text or private filesystem paths; replay remains disabled.
