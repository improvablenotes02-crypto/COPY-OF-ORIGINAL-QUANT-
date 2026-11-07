"""Trusted composition root for owner governance and Delta credential admission."""
from __future__ import annotations
import time
from typing import Callable
from core.accounts.delta_credential_approval import OwnerGovernanceDeltaCredentialApprovalProvider
from core.accounts.owner_governance import AuthenticatedOwnerGovernance, OwnerGovernance
from core.accounts.postgres_owner_governance_repository import AuthenticatedPostgreSQLOwnerGovernanceRepository
from core.accounts.postgres_tenant_services import TenantGovernanceRepository
from core.accounts.request_tenant_authorization import RequestScopedTenantAuthorizer, SessionStatusValidator, TrustedPrincipalSource

class AuthenticatedTenantGovernanceRuntime:
    """Compose owner-only governance and credential admission over one tenant guard.

    Owner identity and tenant DSN routing must come from server-owned deployment
    configuration. The trusted principal source/session validator are shared by
    request-facing governance and the persistence boundary.
    """
    def __init__(self, *, owner_subject_id: str, principal_source: TrustedPrincipalSource,
                 session_validator: SessionStatusValidator,
                 tenant_dsn_resolver: Callable[[str], str], connect_timeout: int = 5,
                 governance_clock: Callable[[], int] = time.time_ns,
                 auth_clock: Callable[[], float] = time.time):
        if not isinstance(owner_subject_id, str) or not owner_subject_id.strip():
            raise ValueError("trusted owner identity is required")
        if not callable(tenant_dsn_resolver):
            raise ValueError("server-configured tenant DSN resolver is required")
        if not callable(getattr(principal_source, "current_principal", None)):
            raise ValueError("trusted principal source is required")
        if not callable(getattr(session_validator, "is_session_active", None)):
            raise ValueError("trusted session validator is required")
        self._principal_source = principal_source
        self._session_validator = session_validator
        self._authorizer = RequestScopedTenantAuthorizer(
            principal_source, session_validator, clock=auth_clock
        )
        persistence = AuthenticatedPostgreSQLOwnerGovernanceRepository(
            tenant_dsn_resolver, connect_timeout=connect_timeout
        )
        self._repository = TenantGovernanceRepository(persistence, self._authorizer)
        domain = OwnerGovernance(
            self._repository, owner_subject_id=owner_subject_id.strip(),
            clock=governance_clock,
        )
        self._owner_governance = AuthenticatedOwnerGovernance(
            domain, principal_source, session_validator, clock=auth_clock
        )
        self._credential_approval = OwnerGovernanceDeltaCredentialApprovalProvider(
            self._repository
        )

    @property
    def owner_governance(self) -> AuthenticatedOwnerGovernance:
        """Request-facing facade; callers cannot supply actor IDs."""
        return self._owner_governance

    @property
    def credential_approval_provider(self) -> OwnerGovernanceDeltaCredentialApprovalProvider:
        """Tenant-authorized approval provider; use only in trusted request/task scope."""
        return self._credential_approval

    @property
    def tenant_authorizer(self) -> RequestScopedTenantAuthorizer:
        return self._authorizer

    @property
    def production_ready(self) -> bool:
        # PostgreSQL adapter remains deliberately non-admissible pending
        # tenant-login provisioning and deployment certification.
        return (
            getattr(self._principal_source, "production_ready", False) is True
            and getattr(self._session_validator, "production_ready", False) is True
            and self._authorizer.production_ready is True
            and getattr(self._repository, "production_ready", False) is True
            and getattr(self._repository, "durable_shared_storage", False) is True
            and getattr(self._repository, "tenant_isolation_enforced", False) is True
        )
