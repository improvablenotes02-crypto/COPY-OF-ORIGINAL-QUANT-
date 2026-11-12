"""Phase 303: credential rotation invalidates sessions and requires re-approval."""
import hashlib
import pytest
from core.accounts.delta_account_registry import (
    CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry,
    SQLiteDeltaAccountRepository, delta_credential_fingerprint,
)
from core.accounts.delta_credential_approval import OwnerGovernanceDeltaCredentialApprovalProvider
from core.accounts.owner_governance import OwnerGovernance, SQLiteOwnerGovernanceRepository

class _TestEncryptionProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("test-only-key", "TEST-ONLY-XOR",
                                  tag + bytes(value ^ 0xA5 for value in plaintext))
    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])

class _RequestIdentity:
    production_ready = False
    def current_subject_id(self, tenant_id: str) -> str:
        assert tenant_id == "tenant-owner"
        return "owner-subject"
    def authorize_tenant(self, tenant_id: str) -> bool:
        return tenant_id == "tenant-owner"

class _ReadOnlyDeltaClient:
    instances = []
    def __init__(self, *, api_key: str, api_secret: str, base_url: str):
        self.api_key, self.api_secret, self.base_url = api_key, api_secret, base_url
        self.closed = False
        type(self).instances.append(self)
    def _get_authenticated_account_id(self):
        return "123456"
    def get_balance(self):
        return {"success": True, "result": []}
    def close(self):
        self.closed = True

def test_rotation_revokes_old_session_and_replacement_requires_owner_reapproval():
    governance_repository = SQLiteOwnerGovernanceRepository()
    account_repository = SQLiteDeltaAccountRepository()
    governance = OwnerGovernance(governance_repository, owner_subject_id="owner-subject",
                                 clock=lambda: 456)
    approval = OwnerGovernanceDeltaCredentialApprovalProvider(governance_repository)
    registry = DeltaAccountRegistry(
        account_repository, _TestEncryptionProvider(),
        exchange_factory=_ReadOnlyDeltaClient, tenant_authorizer=_RequestIdentity(),
        credential_approval_provider=approval,
    )
    _ReadOnlyDeltaClient.instances.clear()
    old_key, old_secret = "owner-key-v1", "owner-secret-v1"
    new_key, new_secret = "owner-key-v2", "owner-secret-v2"
    try:
        metadata = registry.register_account(
            tenant_id="tenant-owner", label="Owner Delta", region="INDIA",
            environment="SANDBOX", api_key=old_key, api_secret=old_secret,
        )
        old_fingerprint = delta_credential_fingerprint(old_key, old_secret)
        old_credential_id = metadata.account_id + "-generation-1"
        governance.submit_credential(
            actor_id="owner-subject", tenant_id="tenant-owner",
            credential_id=old_credential_id, account_id=metadata.account_id,
            fingerprint=old_fingerprint,
        )
        governance.decide_credential(actor_id="owner-subject", tenant_id="tenant-owner",
                                     credential_id=old_credential_id, approve=True)
        old_session = registry.open_read_only_session(
            tenant_id="tenant-owner", account_id=metadata.account_id)
        assert old_session.get_balance()["success"] is True

        rotated = registry.rotate_credentials(
            tenant_id="tenant-owner", account_id=metadata.account_id,
            api_key=new_key, api_secret=new_secret,
        )
        assert rotated.account_id == metadata.account_id
        assert account_repository.get("tenant-owner", metadata.account_id).credential_generation == 2
        with pytest.raises(CredentialVaultError):
            old_session.get_balance()
        old_session.close()

        new_fingerprint = delta_credential_fingerprint(new_key, new_secret)
        assert new_fingerprint != old_fingerprint
        with pytest.raises(CredentialVaultError, match="not owner-approved"):
            registry.open_read_only_session(tenant_id="tenant-owner",
                                             account_id=metadata.account_id)

        new_credential_id = metadata.account_id + "-generation-2"
        governance.submit_credential(
            actor_id="owner-subject", tenant_id="tenant-owner",
            credential_id=new_credential_id, account_id=metadata.account_id,
            fingerprint=new_fingerprint,
        )
        with pytest.raises(CredentialVaultError, match="not owner-approved"):
            registry.open_read_only_session(tenant_id="tenant-owner",
                                             account_id=metadata.account_id)
        governance.decide_credential(actor_id="owner-subject", tenant_id="tenant-owner",
                                     credential_id=new_credential_id, approve=True)
        new_session = registry.open_read_only_session(
            tenant_id="tenant-owner", account_id=metadata.account_id)
        try:
            assert new_session.get_balance()["success"] is True
            assert _ReadOnlyDeltaClient.instances[-1].api_key == new_key
            assert _ReadOnlyDeltaClient.instances[-1].api_secret == new_secret
        finally:
            new_session.close()

        events = account_repository.list_credential_rotation_events(
            "tenant-owner", metadata.account_id)
        assert len(events) == 1
        assert (events[0].previous_generation, events[0].new_generation) == (1, 2)
        assert events[0].previous_key_id == events[0].new_key_id == "test-only-key"
        assert events[0].event_hash
    finally:
        account_repository.close()
        governance_repository.close()
