# Phase 308 — Revisioned Persistent Account Risk State

## Contract

A repository protocol and a local SQLite implementation now support durable per-tenant/per-account risk profiles and state. The new `PersistentAccountRiskCoordinator` reads risk state from the repository for each decision and updates state using optimistic compare-and-swap revisions.

The repository key is `(tenant_id, internal_account_id)`; the stored scope also binds provider account ID, region, environment, and venue. State revisions start at zero and increment atomically. A stale writer cannot overwrite a newer risk state.

## Deployment boundary

`SQLiteAccountRiskRepository` is a local/single-node development adapter. It uses transactions, WAL for file-backed databases, and compare-and-swap updates, but it is not a shared multi-node production database. Production deployment must inject a durable shared implementation of `AccountRiskRepository` with equivalent transactional semantics (for example, a properly configured PostgreSQL service).

The existing in-memory `AccountRiskCoordinator` remains available for local workflows. This new persistent coordinator is not yet wired into live order submission and does not authorize or enable live trading.

## Verification

Tests cover repository reopen persistence, two-connection stale-write rejection, tenant isolation, persisted risk evaluation, non-finite state rejection, and revision validation.
