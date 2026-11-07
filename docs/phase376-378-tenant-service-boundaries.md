# Phases 376–378: tenant-aware application service boundaries

## Phase 376 — trusted repository factory
A single server-side factory constructs the authenticated Delta and governance
PostgreSQL repositories. Its DSN resolver is injected from deployment-owned
configuration; request payloads, JWT claims, and member-controlled profile data
must never choose a DSN, database role, or tenant mapping. The factory and
repositories remain non-production-ready until operational provisioning and
evidence gates are complete.

## Phase 377 — governance tenant guard
The governance persistence adapter is wrapped by a facade that checks the
current verified principal and active session for every tenant-scoped call.
This guard establishes tenant membership only. Owner-only invite, approval,
credential approval, rejection, and revocation decisions remain enforced by
the governance domain service and must never be inferred from tenant membership.

## Phase 378 — background task identity
Background work passes only an opaque job ID to a server-owned principal
resolver. The resolver loads the authenticated job envelope; the runner then
revalidates expiry, membership, and active session immediately before callback
execution. Callers cannot pass a principal object or tenant-membership set.
The runner binds the resolved principal only for the callback scope and restores
the previous context on success or failure. A job without trusted identity fails closed.

## Deployment boundary
These phases do not provision tenant login roles, change migration 003 rollout
readiness, or authorize live execution. Legacy GUC-based repositories remain
unsafe for multi-tenant production. Overall QuantEngine production readiness
remains HOLD.
