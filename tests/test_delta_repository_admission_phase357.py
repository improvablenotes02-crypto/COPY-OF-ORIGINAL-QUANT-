"""Phase 357: production repository durability and tenant-isolation declarations."""
import pytest

from core.accounts.delta_account_registry import (
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)
from tests.test_credential_provider_conformance_phase353 import _TestOnlyConformingProvider


class _ProductionRepositoryTestDouble(SQLiteDeltaAccountRepository):
    """Only a declaration fixture; SQLite is not a production shared database."""

    production_ready = True
    durable_shared_storage = True
    tenant_isolation_enforced = True


class _NoSharedStorageRepository(_ProductionRepositoryTestDouble):
    durable_shared_storage = False


class _NoTenantIsolationRepository(_ProductionRepositoryTestDouble):
    tenant_isolation_enforced = False


class _IncompleteRepositorySurface(_ProductionRepositoryTestDouble):
    get = None


@pytest.mark.parametrize(
    "repository_type",
    [_NoSharedStorageRepository, _NoTenantIsolationRepository, _IncompleteRepositorySurface],
)
def test_production_admission_rejects_incomplete_repository_contract(tmp_path, repository_type):
    repository = repository_type(tmp_path / f"{repository_type.__name__}.sqlite3")
    try:
        with pytest.raises(CredentialVaultError, match="durable shared tenant-isolated repository"):
            DeltaAccountRegistry(
                repository,
                _TestOnlyConformingProvider(),
                require_production_security=True,
            )
    finally:
        repository.close()


def test_sqlite_repository_remains_explicitly_non_production():
    assert SQLiteDeltaAccountRepository.production_ready is False
    assert getattr(SQLiteDeltaAccountRepository, "durable_shared_storage", False) is False
    assert getattr(SQLiteDeltaAccountRepository, "tenant_isolation_enforced", False) is False
