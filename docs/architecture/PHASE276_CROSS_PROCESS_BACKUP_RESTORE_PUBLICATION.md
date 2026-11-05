# Phase 276 — Cross-Process Backup and Restore Publication

## Objective

Certify that the journal's no-clobber publication boundary remains atomic
when independent operating-system processes race to publish to one destination.

## Failure scenario

The backup and restore APIs prepare validated temporary SQLite files before
publishing them. A process-local lock cannot coordinate separate processes.
The final destination must therefore be protected by the filesystem's atomic
no-clobber primitive rather than a check-then-write sequence.

## Tests

Two independent child processes are synchronized behind a filesystem start
gate and race to publish to the same destination:

- Backup race: both create a validated backup from the same live journal.
- Restore race: both restore the same validated source backup to one target.

For each race, exactly one process must report publication success and the
other must receive the expected safe rejection. The winning destination is
then opened and its SQLite integrity and journal records are checked.

Each child has a bounded 15-second gate wait and 25-second completion timeout.
Workers are terminated during test cleanup if they exceed the bound.

## Invariants

- No-overwrite publication has exactly one winner across processes.
- A losing publisher never replaces or truncates the winning destination.
- The resulting backup/restore remains a structurally valid journal.
- No process performs broker/venue I/O or submits/retries orders.
- Explicit overwrite behavior is unchanged; this phase tests the default
  no-clobber path only.

## Limitations

These tests certify the local filesystem used by Ubuntu and Windows CI.
They do not establish equivalent locking/link semantics on network filesystems,
cloud-mounted volumes, or filesystems not supported by SQLite/hard links.
The test does not simulate power loss during directory metadata persistence.

Live order writing remains disarmed.

## Validation

```bash
python -m pytest tests/test_submission_journal_phase276.py -q
python scripts/generate_manifest.py --root . --verify --strict
```
