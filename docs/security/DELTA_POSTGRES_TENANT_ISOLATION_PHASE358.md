# Phase 358 — PostgreSQL tenant-isolation schema

Adds the initial PostgreSQL schema for shared Delta account metadata and credential-rotation audit records. Both tables use forced row-level security (RLS) keyed by transaction-local `quantengine.tenant_id`. Rotation audit rows cannot be updated or deleted.

The PostgreSQL CI integration runs with a non-superuser, NOBYPASSRLS runtime role and verifies tenant A/B isolation, absent cross-tenant update access, audit scoping, immutability, and repeatable migration application.

This is a schema foundation, not the PostgreSQL repository adapter. Runtime connections must never use a superuser, table owner, or BYPASSRLS role; pooled connections must set tenant context transaction-locally and use explicit tenant predicates. This does not yet certify backup/restore, authorization, key custody, external audit, or production deployment. SQLite remains non-production. No real credentials or live orders are used; readiness remains NOT CERTIFIED / HOLD.
