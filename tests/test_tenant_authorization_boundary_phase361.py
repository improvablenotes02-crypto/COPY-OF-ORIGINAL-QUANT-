"""Phase 361: production Delta registry enforces trusted tenant authorization."""
import pytest

from core.accounts.delta_account_registry import (
    AccountScopeError,
    CredentialVaultError,
    DeltaAccountRegistry,
)
from tests.test_credential_provider_conformance_phase353 import _TestOnlyConformingProvider
from tests.test_delta_credential_provider_admission_phase356 import _ProductionDeclaredTestRepository


class _TenantAuthorizer:
    production_ready = True

    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.fail = False

    def authorize_tenant(self, tenant_id):
        if self.fail:
            raise RuntimeError("private auth provider diagnostic")
        return tenant_id in self.allowed


def _registry(tmp_path, authorizer):
    repository = _ProductionDeclaredTestRepository(tmp_path / "tenant-auth.sqlite3")
    registry = DeltaAccountRegistry(
        repository,
        _TestOnlyConformingProvider(),
        require_production_security=True,
        tenant_authorizer=authorizer,
    )
    return repository, registry


def test_production_admission_requires_trusted_tenant_authorizer(tmp_path):
    repository = _ProductionDeclaredTestRepository(tmp_path / "missing-authorizer.sqlite3")
    try:
        with pytest.raises(CredentialVaultError, match="trusted tenant authorization provider"):
            DeltaAccountRegistry(
                repository,
                _TestOnlyConformingProvider(),
                require_production_security=True,
            )
    finally:
        repository.close()


def test_authorizer_blocks_cross_tenant_operations_before_storage_or_encryption(tmp_path):
    authorizer = _TenantAuthorizer({"tenant-a"})
    repository, registry = _registry(tmp_path, authorizer)
    try:
        metadata = registry.register_account(
            tenant_id="tenant-a", label="allowed", region="INDIA",
            environment="SANDBOX", api_key="test-key-a", api_secret="test-secret-a",
        )
        assert registry.list_accounts("tenant-a") == [metadata]
        # The caller cannot select another tenant merely by changing an argument.
        before = registry._encryption_provider.counter
        with pytest.raises(AccountScopeError, match="not authorized"):
            registry.register_account(
                tenant_id="tenant-b", label="denied", region="INDIA",
                environment="SANDBOX", api_key="test-key-b", api_secret="test-secret-b",
            )
        with pytest.raises(AccountScopeError, match="not authorized"):
            registry.list_accounts("tenant-b")
        assert registry._encryption_provider.counter == before
        assert repository.list_for_tenant("tenant-b") == []
    finally:
        repository.close()


def test_authorization_provider_failure_and_non_boolean_result_fail_closed(tmp_path):
    authorizer = _TenantAuthorizer({"tenant-a"})
    repository, registry = _registry(tmp_path, authorizer)
    try:
        authorizer.fail = True
        with pytest.raises(AccountScopeError, match="could not be verified") as caught:
            registry.list_accounts("tenant-a")
        assert "private auth provider diagnostic" not in str(caught.value)
        authorizer.fail = False
        authorizer.authorize_tenant = lambda tenant_id: "yes"
        with pytest.raises(AccountScopeError, match="not authorized"):
            registry.list_accounts("tenant-a")
    finally:
        repository.close()
