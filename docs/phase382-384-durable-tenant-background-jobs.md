# Phases 382–384: durable one-shot tenant background jobs

## Phase 382 — server-owned job envelope
Background jobs persist tenant, subject, session, membership set and expiry in
a server-side envelope. Workers receive only an opaque job ID and cannot select
or override tenant identity. Enqueue derives identity from the verified
request principal and checks active session and tenant membership.

## Phase 383 — atomic durable claim
Added a SQLite queue with WAL, FULL synchronous writes, bounded busy timeout,
atomic BEGIN IMMEDIATE claims, and terminal SUCCEEDED/FAILED/EXPIRED states.
A job can be claimed once. A crash after claim leaves RUNNING and is never
automatically replayed because callback side effects may be ambiguous.

## Phase 384 — runtime dispatch and concurrency
The authenticated tenant runtime now owns enqueue and worker dispatch.
Adversarial tests cover tenant override, expiry, callback failure, crash after
claim, session revocation, and concurrent workers racing for one job.

## Deployment limits
The SQLite implementation is single-host and deliberately
production_ready=False; it is not a distributed queue and does not guarantee
exactly-once external side effects. RUNNING jobs need explicit operator
reconciliation. Multi-node deployment requires a shared transactional queue.
PostgreSQL tenant login provisioning and production OIDC/session adapters are
still outstanding. Live execution remains disarmed.
