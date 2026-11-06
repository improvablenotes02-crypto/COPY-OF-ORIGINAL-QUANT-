"""Phase 345: credential generation changes have atomic, scoped audit evidence."""

import hashlib

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase345-new-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class _IdentityProbe:
    def __init__(self, **kwargs):
        self.close_calls = 0

    def _get_authenticated_account_id(self):
        return "987654"

    def close(self):
        self.close_calls += 1


def make_registry(repository, probes):
    def factory(**kwargs):
        probe = _IdentityProbe(**kwargs)
        probes.append(probe)
        return probe
    return DeltaAccountRegistry(repository, _TestOnlyProvider(), exchange_factory=factory)


def test_successful_rotation_writes_scoped_audit_event(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "rotation-audit.sqlite3")
    probes = []
    registry = make_registry(repository, probes)
    metadata = registry.register_account(
        tenant_id="tenant-phase345", label="audit", region="INDIA",
        environment="SANDBOX", api_key="old-api-key", api_secret="old-api-secret",
    )
    before = repository.get("tenant-phase345", metadata.account_id)
    try:
        registry.rotate_credentials(
            tenant_id="tenant-phase345", account_id=metadata.account_id,
            api_key="new-api-key", api_secret="new-api-secret",
        )
        events = repository.list_credential_rotation_events(
            "tenant-phase345", metadata.account_id
        )
        assert len(events) == 1
        event = events[0]
        assert event.tenant_id == "tenant-phase345"
        assert event.account_id == metadata.account_id
        assert event.previous_generation == 1
        assert event.new_generation == 2
        assert event.previous_key_id == before.key_id
        assert event.new_key_id == "phase345-new-key"
        assert event.occurred_at_ns > before.updated_at_ns
        assert "old-api-secret" not in repr(event)
        assert "new-api-secret" not in repr(event)
        assert probes[0].close_calls == 1
    finally:
        repository.close()


def test_audit_insert_failure_rolls_back_credential_replacement(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "rotation-audit-rollback.sqlite3")
    probes = []
    registry = make_registry(repository, probes)
    metadata = registry.register_account(
        tenant_id="tenant-phase345-rollback", label="audit-rollback", region="INDIA",
        environment="SANDBOX", api_key="original-key", api_secret="original-secret",
    )
    before = repository.get("tenant-phase345-rollback", metadata.account_id)
    repository._connection.execute(
        """
        CREATE TRIGGER reject_rotation_audit
        BEFORE INSERT ON delta_credential_rotation_events
        BEGIN
            SELECT RAISE(ABORT, 'simulated audit storage failure');
        END
        """
    )
    try:
        with pytest.raises(CredentialVaultError, match="could not be committed"):
            registry.rotate_credentials(
                tenant_id="tenant-phase345-rollback", account_id=metadata.account_id,
                api_key="replacement-key", api_secret="replacement-secret",
            )
        after = repository.get("tenant-phase345-rollback", metadata.account_id)
        assert after == before
        assert repository.list_credential_rotation_events(
            "tenant-phase345-rollback", metadata.account_id
        ) == []
        assert probes[0].close_calls == 1
    finally:
        repository.close()
