"""Phase 347: rotation audit events carry a verified per-account hash chain."""

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
        return CiphertextEnvelope("phase347-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


class _IdentityProbe:
    def __init__(self, **kwargs):
        pass

    def _get_authenticated_account_id(self):
        return "987654"

    def close(self):
        pass


def test_multiple_rotations_form_a_verified_hash_chain(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "audit-chain.sqlite3")
    registry = DeltaAccountRegistry(
        repository, _TestOnlyProvider(), exchange_factory=_IdentityProbe
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase347", label="chain", region="INDIA",
        environment="SANDBOX", api_key="key-0", api_secret="secret-0",
    )
    try:
        for index in (1, 2):
            registry.rotate_credentials(
                tenant_id="tenant-phase347", account_id=metadata.account_id,
                api_key=f"key-{index}", api_secret=f"secret-{index}",
            )
        events = repository.list_credential_rotation_events(
            "tenant-phase347", metadata.account_id
        )
        assert [event.previous_generation for event in events] == [1, 2]
        assert [event.new_generation for event in events] == [2, 3]
        assert events[0].previous_event_hash == "0" * 64
        assert events[1].previous_event_hash == events[0].event_hash
        assert all(len(event.event_hash) == 64 for event in events)
    finally:
        repository.close()


def test_offline_audit_field_tampering_is_detected(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "audit-tamper.sqlite3")
    registry = DeltaAccountRegistry(
        repository, _TestOnlyProvider(), exchange_factory=_IdentityProbe
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase347-tamper", label="tamper", region="INDIA",
        environment="SANDBOX", api_key="key-0", api_secret="secret-0",
    )
    try:
        registry.rotate_credentials(
            tenant_id="tenant-phase347-tamper", account_id=metadata.account_id,
            api_key="key-1", api_secret="secret-1",
        )
        event = repository.list_credential_rotation_events(
            "tenant-phase347-tamper", metadata.account_id
        )[0]
        repository._connection.execute("DROP TRIGGER prevent_delta_credential_event_update")
        repository._connection.execute(
            "UPDATE delta_credential_rotation_events SET new_key_id = 'offline-tamper' "
            "WHERE event_id = ?",
            (event.event_id,),
        )
        with pytest.raises(CredentialVaultError, match="integrity check failed"):
            repository.list_credential_rotation_events(
                "tenant-phase347-tamper", metadata.account_id
            )
    finally:
        repository.close()
