Phase 269 — Atomic no-clobber backup and restore publication

The Phase 268 existence-check followed by os.replace had a time-of-check/time-of-use race when overwrite=False: two processes could both observe an absent destination and a later replace could silently overwrite the first publication.

Phase 269 changes no-overwrite publication to an atomic same-filesystem hard-link create. The operation either creates the destination or fails because it already exists. It never falls back to check-then-replace; filesystems that cannot provide hard links fail closed with SubmissionJournalError. The temporary file is removed after a successful link. Explicit overwrite=True retains atomic os.replace behavior.

The same publication primitive is used by backup_to and restore_from. Tests exercise concurrent competing backup and restore publishers and verify that exactly one caller wins, plus the explicit overwrite path. This is an atomic filesystem publication guarantee, not a guarantee against privileged filesystem tampering, hardware failure, or unsupported network filesystem semantics.

Live order writing remains disarmed. Backup restoration still does not authorize resubmission; unresolved records require venue reconciliation.
