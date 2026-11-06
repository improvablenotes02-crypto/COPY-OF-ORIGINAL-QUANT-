# Phase 274 — Read Isolation and Cross-Process Reservation

## Scope

Phase 274 hardens SQLite concurrency boundaries in the durable submission
journal. Diagnostic and query operations (validate_integrity,
backup-file validation, health_report, unresolved, and get) now use deferred
BEGIN read transactions. Mutating operations (reserve and transition)
retain BEGIN IMMEDIATE so uniqueness checks and lifecycle updates serialize
before writing.

## Consistency and locking

Each read operation performs integrity validation and its result query within
the same SQLite transaction, preserving a consistent snapshot without
requesting a RESERVED write lock. This allows health diagnostics to proceed
while another connection holds a RESERVED writer lock (before its commit).
SQLite's normal journal-mode locking still governs commit behavior; this is
not a claim of lock-free reads or support for filesystems with unsafe SQLite
locking semantics.

Cross-process duplicate reservations are serialized by SQLite's primary-key
constraint and transaction locking. For a client order ID, at most one process
can persist the PREPARED reservation; all competing attempts return False.
The journal remains fail-closed on lock timeout or database errors.

## Safety

- No broker/venue I/O is added.
- No retry or dispatch behavior is added.
- reserve and transition remain durable write transactions.
- This phase does not authorize live order writing; live execution remains
  disarmed and separately gated.

## Validation

    python -m pytest tests/test_submission_journal_phase274.py -q
    python scripts/generate_manifest.py --root . --verify --strict

The tests cover a health report while another connection holds a RESERVED
writer lock and a synchronized two-process race for one client order ID.
