"""Phase 343: account metadata revisions remain monotonic if the wall clock stalls."""

from core.accounts import delta_account_registry as registry_module
from core.accounts.delta_account_registry import SQLiteDeltaAccountRepository


def test_provider_identity_binding_advances_version_when_clock_does_not(tmp_path, monkeypatch):
    repository = SQLiteDeltaAccountRepository(tmp_path / "monotonic-binding.sqlite3")
    repository.save(
        registry_module.EncryptedDeltaAccount(
            account_id="account-phase343",
            tenant_id="tenant-phase343",
            venue="delta",
            region="INDIA",
            environment="SANDBOX",
            label="monotonic",
            provider_account_id=None,
            key_id="test-key",
            algorithm="TEST-ONLY",
            ciphertext=b"opaque",
            created_at_ns=100,
            updated_at_ns=200,
        )
    )
    monkeypatch.setattr(registry_module.time, "time_ns", lambda: 200)
    try:
        repository.bind_provider_identity(
            "tenant-phase343", "account-phase343", "987654"
        )
        current = repository.get("tenant-phase343", "account-phase343")
        assert current.provider_account_id == "987654"
        assert current.updated_at_ns == 201
        assert current.credential_generation == 1
    finally:
        repository.close()
