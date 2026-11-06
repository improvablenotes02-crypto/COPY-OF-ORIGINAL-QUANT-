"""Phase 346: credential rotation audit evidence is append-only and tenant-scoped."""

import hashlib
import sqlite3

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase346-key", "TEST-ONLY", tag + plaintext)

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


def test_rotation_audit_events_are_immutable_and_tenant_scoped(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "immutable-audit.sqlite3")
    registry = DeltaAccountRegistry(
        repository, _TestOnlyProvider(), exchange_factory=_IdentityProbe
    )
    metadata = registry.register_account(
        tenant_id="tenant-phase346", label="immutable", region="INDIA",
        environment="SANDBOX", api_key="api-key", api_secret="api-secret",
    )
    try:
        registry.rotate_credentials(
            tenant_id="tenant-phase346", account_id=metadata.account_id,
            api_key="rotated-key", api_secret="rotated-secret",
        )
        events = repository.list_credential_rotation_events(
            "tenant-phase346", metadata.account_id
        )
        assert len(events) == 1
        assert repository.list_credential_rotation_events(
            "other-tenant", metadata.account_id
        ) == []
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            repository._connection.execute(
                "UPDATE delta_credential_rotation_events SET new_key_id = 'tampered' "
                "WHERE event_id = ?",
                (events[0].event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            repository._connection.execute(
                "DELETE FROM delta_credential_rotation_events WHERE event_id = ?",
                (events[0].event_id,),
            )
        assert repository.list_credential_rotation_events(
            "tenant-phase346", metadata.account_id
        ) == events
    finally:
        repository.close()
