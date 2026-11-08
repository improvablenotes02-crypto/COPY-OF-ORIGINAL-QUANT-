"""Trusted composition root for owner governance and Delta credential admission."""
from __future__ import annotations
import time
from typing import Callable
from core.accounts.delta_credential_approval import OwnerGovernanceDeltaCredentialApprovalProvider
from core.accounts.owner_governance import AuthenticatedOwnerGovernance, OwnerGovernance
from core.accounts.postgres_owner_governance_repository import AuthenticatedPostgreSQLOwnerGovernanceRepository
from core.accounts.postgres_tenant_services import TenantGovernanceRepository
from core.accounts.request_tenant_authorization import RequestScopedTenantAuthorizer, SessionStatusValidator, TrustedPrincipalSource
from core.accounts.postgres_tenant_services import TenantBackgroundTaskRunner, TrustedBackgroundJobStore
from core.accounts.postgres_tenant_services import TenantDeltaAccountRepository
from core.accounts.postgres_delta_account_repository import AuthenticatedPostgreSQLDeltaAccountRepository
from core.accounts.delta_account_registry import DeltaAccountRegistry, EncryptionProvider
from core.accounts.owner_governance_api import create_owner_governance_server

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
                 auth_clock: Callable[[], float] = time.time,
                 background_job_store: TrustedBackgroundJobStore | None = None):
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
        self._tenant_dsn_resolver = tenant_dsn_resolver
        self._connect_timeout = connect_timeout
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
        self._background_job_store = background_job_store
        self._background_runner = TenantBackgroundTaskRunner(background_job_store, self._authorizer) if background_job_store is not None else None
        self._delta_account_registry = None

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
    def delta_account_registry(self) -> DeltaAccountRegistry | None:
        """Registry owned by this runtime after API composition."""
        return self._delta_account_registry

    def create_owner_governance_server(
        self, *, encryption_provider: EncryptionProvider,
        host: str = "127.0.0.1", port: int = 0,
        allow_nonproduction: bool = False, max_workers: int = 16,
        request_timeout: float = 10.0,
    ):
        """Build the owner API and encrypted Delta registry with shared auth guards.

        principal_source must be the OIDC source used by bind_access_token.
        Encryption and tenant routing remain deployment-owned dependencies.
        Non-production mode is still loopback-only and must be explicitly opted in.
        """
        if encryption_provider is None:
            raise ValueError("an approved credential encryption provider is required")
        if not isinstance(allow_nonproduction, bool):
            raise ValueError("allow_nonproduction must be boolean")
        delta_persistence = AuthenticatedPostgreSQLDeltaAccountRepository(
            self._tenant_dsn_resolver, connect_timeout=self._connect_timeout
        )
        delta_repository = TenantDeltaAccountRepository(
            delta_persistence, self._authorizer
        )
        registry = DeltaAccountRegistry(
            delta_repository, encryption_provider,
            tenant_authorizer=self._authorizer,
            credential_approval_provider=self._credential_approval,
        )
        server = create_owner_governance_server(
            self._owner_governance, host=host, port=port,
            max_workers=max_workers, request_timeout=request_timeout,
            allow_nonproduction=allow_nonproduction, account_registry=registry,
        )
        self._delta_account_registry = registry
        return server

    def enqueue_background_job(self, tenant_id: str, *, ttl_seconds: float = 300.0) -> str:
        """Create a durable job envelope from the current verified request context."""
        if self._background_job_store is None:
            raise RuntimeError("background job store is not configured")
        try:
            principal = self._principal_source.current_principal()
            if self._authorizer.authorize_tenant(tenant_id) is not True:
                raise ValueError("tenant scope denied")
            return self._background_job_store.enqueue(principal, tenant_id, ttl_seconds=ttl_seconds)
        except Exception:
            raise PermissionError("background task could not be authorized") from None

    def run_background_job(self, job_id: str, callback, *args, **kwargs):
        """Worker dispatch accepts an opaque job ID and no caller-selected tenant."""
        if self._background_runner is None:
            raise RuntimeError("background job store is not configured")
        return self._background_runner.run(job_id, callback, *args, **kwargs)

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
            and self._background_job_store is not None
            and getattr(self._background_job_store, "production_ready", False) is True
        )
