"""Trusted construction and execution boundaries for tenant-scoped services.

The DSN resolver must be created from server-controlled deployment configuration.
Never derive database role names, DSNs, or tenant mappings from request data.
"""
from __future__ import annotations

from typing import Callable

from core.accounts.delta_account_registry import AccountScopeError
from core.accounts.oidc_tenant_principal import AuthenticatedPrincipal
from core.accounts.postgres_delta_account_repository import AuthenticatedPostgreSQLDeltaAccountRepository
from core.accounts.postgres_owner_governance_repository import (
    AuthenticatedPostgreSQLOwnerGovernanceRepository,
)
from core.accounts.request_tenant_authorization import (
    RequestScopedTenantAuthorizer,
    TrustedPrincipalSource,
    SessionStatusValidator,
)


class TenantDeltaAccountRepository:
    """Tenant-authorized facade; database identity is independently checked below."""
    production_ready = False
    durable_shared_storage = True
    tenant_isolation_enforced = True

    def __init__(self, repository, authorizer):
        self._repository = repository
        self._authorizer = authorizer

    def _require_tenant(self, tenant_id: str) -> None:
        if self._authorizer.authorize_tenant(tenant_id) is not True:
            raise AccountScopeError("tenant is not authorized for this operation")

    def save(self, record):
        self._require_tenant(record.tenant_id)
        return self._repository.save(record)

    def get(self, tenant_id, account_id):
        self._require_tenant(tenant_id)
        return self._repository.get(tenant_id, account_id)

    def list_for_tenant(self, tenant_id):
        self._require_tenant(tenant_id)
        return self._repository.list_for_tenant(tenant_id)

    def delete(self, tenant_id, account_id):
        self._require_tenant(tenant_id)
        return self._repository.delete(tenant_id, account_id)

    def bind_provider_identity(self, tenant_id, account_id, provider_account_id):
        self._require_tenant(tenant_id)
        return self._repository.bind_provider_identity(tenant_id, account_id, provider_account_id)

    def replace_credentials(self, record, *, expected_generation, expected_updated_at_ns):
        self._require_tenant(record.tenant_id)
        return self._repository.replace_credentials(
            record, expected_generation=expected_generation,
            expected_updated_at_ns=expected_updated_at_ns,
        )

    def list_credential_rotation_events(self, tenant_id, account_id):
        self._require_tenant(tenant_id)
        return self._repository.list_credential_rotation_events(tenant_id, account_id)


class TenantGovernanceRepository:
    """Tenant-authorized facade over owner-governance persistence.

    This enforces tenant membership, not owner permissions. The governance
    domain service must still enforce owner-only decisions and audit semantics.
    """
    production_ready = False

    def __init__(self, repository, authorizer):
        self._repository = repository
        self._authorizer = authorizer

    def _require_tenant(self, tenant_id: str) -> None:
        if self._authorizer.authorize_tenant(tenant_id) is not True:
            raise AccountScopeError("tenant is not authorized for this operation")

    def invite(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.invite(tenant, *args, **kwargs)

    def decide_membership(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.decide_membership(tenant, *args, **kwargs)

    def membership(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.membership(tenant, *args, **kwargs)

    def submit_credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.submit_credential(tenant, *args, **kwargs)

    def decide_credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.decide_credential(tenant, *args, **kwargs)

    def credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.credential(tenant, *args, **kwargs)

    def revoke_credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.revoke_credential(tenant, *args, **kwargs)

    def credentials_for_account_fingerprint(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.credentials_for_account_fingerprint(tenant, *args, **kwargs)

    def audit_events(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.audit_events(tenant, *args, **kwargs)


class AuthenticatedTenantRepositoryFactory:
    """Build repositories only with trusted, server-configured tenant routing."""

    production_ready = False

    def __init__(
        self,
        *,
        principal_source: TrustedPrincipalSource,
        session_validator: SessionStatusValidator,
        tenant_dsn_resolver: Callable[[str], str],
        connect_timeout: int = 5,
    ):
        if not callable(tenant_dsn_resolver):
            raise ValueError("server-configured tenant DSN resolver is required")
        self._resolver = tenant_dsn_resolver
        self._timeout = connect_timeout
        self._authorizer = RequestScopedTenantAuthorizer(
            principal_source, session_validator
        )

    @property
    def tenant_authorizer(self):
        return self._authorizer

    def delta_repository(self):
        persistence = AuthenticatedPostgreSQLDeltaAccountRepository(
            self._resolver, connect_timeout=self._timeout
        )
        return TenantDeltaAccountRepository(persistence, self._authorizer)

    def _governance_persistence(self):
        return AuthenticatedPostgreSQLOwnerGovernanceRepository(
            self._resolver, connect_timeout=self._timeout
        )

    def governance_repository(self):
        return TenantGovernanceRepository(
            self._governance_persistence(), self._authorizer
        )


class TenantBackgroundTaskRunner:
    """Revalidate a trusted principal and tenant before running a background task.

    Call only after loading a server-authenticated job envelope. Never construct
    AuthenticatedPrincipal from task payload fields or client-supplied claims.
    """
    production_ready = False

    def __init__(self, authorizer: RequestScopedTenantAuthorizer):
        if not isinstance(authorizer, RequestScopedTenantAuthorizer):
            raise ValueError("trusted request-scoped tenant authorizer is required")
        self._authorizer = authorizer

    def run(self, principal: AuthenticatedPrincipal, tenant_id: str, callback, *args, **kwargs):
        from core.accounts.request_tenant_authorization import bind_authenticated_principal
        if not isinstance(principal, AuthenticatedPrincipal):
            raise AccountScopeError("background task principal could not be verified")
        if not callable(callback):
            raise ValueError("background task callback must be callable")
        with bind_authenticated_principal(principal):
            if self._authorizer.authorize_tenant(tenant_id) is not True:
                raise AccountScopeError("background task tenant is not authorized")
            return callback(*args, **kwargs)
