"""Phase 303: prove credential rotation requires fresh owner approval."""
import hashlib

import pytest

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    CredentialVaultError,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
    delta_credential_fingerprint,
)
from core.accounts.delta_credential_approval import (
    OwnerGovernanceDeltaCredentialApprovalProvider,
)
from core.accounts.owner_governance import OwnerGovernance, SQLiteOwnerGovernanceRepository


class _TestEncryptionProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope(
            "test-only-key", "TEST-ONLY-XOR",
            tag + bytes(value ^ 0xA5 for value in plaintext),
        )

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])


class _OwnerIdentity:
    production_ready = False

    def authorize_tenant(self, tenant_id: str) -> bool:
        return tenant_id == "tenant-owner"

    def current_subject_id(self, tenant_id: str) -> str:
        if not self.authorize_tenant(tenant_id):
            raise PermissionError("tenant denied")
        return "owner-subject"


class _RotationAwareDeltaClient:
    instances = []

    def __init__(self, *, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.closed = False
        type(self).instances.append(self)

    def _get_authenticated_account_id(self):
        return "123456"

    def get_balance(self):
        return {"success": True, "available": 42}

    def close(self):
        self.closed = True


def test_rotation_invalidates_old_session_and_requires_new_owner_approval():
    governance_repository = SQLiteOwnerGovernanceRepository()
    account_repository = SQLiteDeltaAccountRepository()
    governance = OwnerGovernance(
        governance_repository, owner_subject_id="owner-subject", clock=lambda: 456
    )
    approval = OwnerGovernanceDeltaCredentialApprovalProvider(governance_repository)
    registry = DeltaAccountRegistry(
        account_repository,
        _TestEncryptionProvider(),
        exchange_factory=_RotationAwareDeltaClient,
        tenant_authorizer=_OwnerIdentity(),
        credential_approval_provider=approval,
    )
    _RotationAwareDeltaClient.instances.clear()

    old_key, old_secret = "owner-key-generation-1", "owner-secret-generation-1"
    new_key, new_secret = "owner-key-generation-2", "owner-secret-generation-2"
    try:
        metadata = registry.register_account(
            tenant_id="tenant-owner", label="personal Delta",
            region="INDIA", environment="SANDBOX",
            api_key=old_key, api_secret=old_secret,
        )
        governance.submit_credential(
            actor_id="owner-subject", tenant_id="tenant-owner",
            credential_id=f"{metadata.account_id}:generation:1",
            account_id=metadata.account_id,
            fingerprint=delta_credential_fingerprint(old_key, old_secret),
        )
        governance.decide_credential(
            actor_id="owner-subject", tenant_id="tenant-owner",
            credential_id=f"{metadata.account_id}:generation:1", approve=True,
        )

        old_session = registry.open_read_only_session(
            tenant_id="tenant-owner", account_id=metadata.account_id,
        )
        assert old_session.get_balance()["success"] is True

        rotated = registry.rotate_credentials(
            tenant_id="tenant-owner", account_id=metadata.account_id,
            api_key=new_key, api_secret=new_secret,
        )
        stored = account_repository.get("tenant-owner", metadata.account_id)
        assert stored is not None
        assert stored.credential_generation == 2
        assert rotated.provider_account_id == "123456"

        events = account_repository.list_credential_rotation_events(
            "tenant-owner", metadata.account_id
        )
        assert len(events) == 1
        assert events[0].previous_generation == 1
        assert events[0].new_generation == 2
        assert events[0].previous_key_id == "test-only-key"
        assert events[0].new_key_id == "test-only-key"

        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            old_session.get_balance()

        # The old approval is fingerprint-specific and cannot authorize the replacement.
        with pytest.raises(CredentialVaultError, match="not owner-approved"):
            registry.open_read_only_session(
                tenant_id="tenant-owner", account_id=metadata.account_id,
            )

        governance.submit_credential(
            actor_id="owner-subject", tenant_id="tenant-owner",
            credential_id=f"{metadata.account_id}:generation:2",
            account_id=metadata.account_id,
            fingerprint=delta_credential_fingerprint(new_key, new_secret),
        )
        with pytest.raises(CredentialVaultError, match="not owner-approved"):
            registry.open_read_only_session(
                tenant_id="tenant-owner", account_id=metadata.account_id,
            )

        governance.decide_credential(
            actor_id="owner-subject", tenant_id="tenant-owner",
            credential_id=f"{metadata.account_id}:generation:2", approve=True,
        )
        new_session = registry.open_read_only_session(
            tenant_id="tenant-owner", account_id=metadata.account_id,
        )
        try:
            assert new_session.get_balance() == {"success": True, "available": 42}
            with pytest.raises(CredentialVaultError, match="no longer authorized"):
                old_session.get_balance()
        finally:
            new_session.close()
            old_session.close()

        assert all(client.closed for client in _RotationAwareDeltaClient.instances)
    finally:
        account_repository.close()
        governance_repository.close()
