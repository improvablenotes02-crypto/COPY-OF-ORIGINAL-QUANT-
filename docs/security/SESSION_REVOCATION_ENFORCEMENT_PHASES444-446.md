# Session revocation enforcement (phases 444–446)

The authenticated tenant governance runtime already delegates session checks to
an injected `SessionStatusValidator`. This increment adds a composable,
fail-closed implementation that requires both the upstream identity provider
to report the session active and a local revocation store to report that the
(subject, session) pair is not revoked.

`SessionRevocationCoordinator` accepts only an `AuthenticatedPrincipal`
created by trusted authentication middleware. It does not accept tenant IDs,
actor IDs, session IDs, or revocation claims from request payloads. Repeated
revocation is delegated to the store and should be idempotent.

**Deployment contract:** the store must be durable, shared across all API and
worker processes, strongly consistent for reads after writes, protected from
tenant/user cross-scope access, and must fail closed during outages. A store
that merely caches revocations or is process-local is not production-ready.
The wrapper's `production_ready` flag is true only when both injected
dependencies explicitly declare readiness.

This is an enforcement adapter and test contract, not a deployed persistence
implementation. It does not claim to terminate an external identity-provider
session; production composition must also call the provider's supported
session-revocation endpoint and preserve the local deny entry until token
expiry. Existing JWT expiry and membership-resolution checks remain required.
