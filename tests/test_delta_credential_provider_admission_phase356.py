"""Phase 356: production credential admission runs provider conformance once."""
import pytest

from core.accounts.delta_account_registry import (
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)
from tests.test_credential_provider_conformance_phase353 import (
    _BrokenProvider,
    _TestOnlyConformingProvider,
)


class _ProductionDeclaredTestRepository(SQLiteDeltaAccountRepository):
    """Test-only repository declaration; not a production storage backend."""

    production_ready = True
    durable_shared_storage = True
    tenant_isolation_enforced = True


class _AllowTenantAuthorizer:
    production_ready = True

    def authorize_tenant(self, tenant_id):
        return True

class _AllowOwnerApproval:
    production_ready = True

    def is_approved(self, *, tenant_id, account_id, fingerprint):
        return True


def test_production_admission_requires_behavioral_provider_conformance(tmp_path):
    repository = _ProductionDeclaredTestRepository(tmp_path / "provider-admission.sqlite3")
    try:
        with pytest.raises(CredentialVaultError, match="behavioral conformance"):
            DeltaAccountRegistry(
                repository,
                _BrokenProvider(),
                require_production_security=True,
                tenant_authorizer=_AllowTenantAuthorizer(),
                credential_approval_provider=_AllowOwnerApproval(),
            )
        assert repository.list_for_tenant("tenant-phase356") == []
    finally:
        repository.close()


def test_conforming_provider_is_assessed_once_and_not_per_account_write(tmp_path):
    repository = _ProductionDeclaredTestRepository(tmp_path / "provider-once.sqlite3")
    provider = _TestOnlyConformingProvider()
    registry = DeltaAccountRegistry(
        repository, provider, require_production_security=True,
        tenant_authorizer=_AllowTenantAuthorizer(),
        credential_approval_provider=_AllowOwnerApproval(),
    )
    try:
        # Two encryptions are the fixed conformance assessment vector.
        assert provider.counter == 2
        registry.register_account(
            tenant_id="tenant-phase356", label="sandbox-test",
            region="INDIA", environment="SANDBOX",
            api_key="test-only-api-key", api_secret="test-only-api-secret",
        )
        # Registration performs one real account-envelope encryption; it does
        # not rerun the four-operation conformance probe on every write.
        assert provider.counter == 3
    finally:
        repository.close()


def test_replacing_provider_object_invalidates_cached_conformance(tmp_path):
    repository = _ProductionDeclaredTestRepository(tmp_path / "provider-replaced.sqlite3")
    registry = DeltaAccountRegistry(
        repository, _TestOnlyConformingProvider(),
        require_production_security=True,
        tenant_authorizer=_AllowTenantAuthorizer(),
        credential_approval_provider=_AllowOwnerApproval(),
    )
    try:
        registry._encryption_provider = _BrokenProvider()
        with pytest.raises(CredentialVaultError, match="behavioral conformance"):
            registry._assert_production_security_contract()
    finally:
        repository.close()
