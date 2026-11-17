"""Phase 302: exercise the owner's personal Delta credential path end to end."""
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
from core.accounts.owner_governance import (
    OwnerAuthorizationError,
    OwnerGovernance,
    SQLiteOwnerGovernanceRepository,
)


class _TestEncryptionProvider:
    """Deterministic test-only envelope; never use outside tests."""

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope(
            "test-only-key",
            "TEST-ONLY-XOR",
            tag + bytes(value ^ 0xA5 for value in plaintext),
        )

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])


class _RequestIdentity:
    """Mutable trusted-principal stand-in for exercising subject changes."""

    production_ready = False

    def __init__(self, subject_id: str):
        self.subject_id = subject_id

    def authorize_tenant(self, tenant_id: str) -> bool:
        return tenant_id == "tenant-owner"

    def current_subject_id(self, tenant_id: str) -> str:
        if not self.authorize_tenant(tenant_id):
            raise PermissionError("tenant is not authorized")
        return self.subject_id


class _ReadOnlyDeltaClient:
    instances = []

    def __init__(self, *, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.closed = False
        type(self).instances.append(self)

    def get_balance(self):
        return {"success": True, "result": [{"asset": "USD", "available_balance": 10}]}

    def close(self):
        self.closed = True


def test_owner_personal_credentials_require_explicit_owner_approval_and_remain_subject_bound():
    governance_repository = SQLiteOwnerGovernanceRepository()
    account_repository = SQLiteDeltaAccountRepository()
    identity = _RequestIdentity("owner-subject")
    governance = OwnerGovernance(
        governance_repository,
        owner_subject_id="owner-subject",
        clock=lambda: 123,
    )
    approval = OwnerGovernanceDeltaCredentialApprovalProvider(governance_repository)
    registry = DeltaAccountRegistry(
        account_repository,
        _TestEncryptionProvider(),
        exchange_factory=_ReadOnlyDeltaClient,
        tenant_authorizer=identity,
        credential_approval_provider=approval,
    )
    _ReadOnlyDeltaClient.instances.clear()

    api_key = "owner-personal-key"
    api_secret = "owner-personal-secret"
    try:
        # Owner registration does not require an artificial member record.
        metadata = registry.register_account(
            tenant_id="tenant-owner",
            label="Owner's personal Delta account",
            region="INDIA",
            environment="SANDBOX",
            api_key=api_key,
            api_secret=api_secret,
        )
        assert governance_repository.membership("tenant-owner", "owner-subject") is None

        record = account_repository.get("tenant-owner", metadata.account_id)
        assert record is not None
        assert api_key.encode() not in record.ciphertext
        assert api_secret.encode() not in record.ciphertext

        fingerprint = delta_credential_fingerprint(api_key, api_secret)
        governance.submit_credential(
            actor_id="owner-subject",
            tenant_id="tenant-owner",
            credential_id=metadata.account_id,
            account_id=metadata.account_id,
            fingerprint=fingerprint,
        )

        # Pending credentials cannot instantiate a Delta client.
        with pytest.raises(CredentialVaultError, match="not owner-approved"):
            registry.open_read_only_session(
                tenant_id="tenant-owner", account_id=metadata.account_id
            )
        assert _ReadOnlyDeltaClient.instances == []

        # Only the configured owner can approve the pending personal key.
        with pytest.raises(OwnerAuthorizationError):
            governance.decide_credential(
                actor_id="untrusted-member",
                tenant_id="tenant-owner",
                credential_id=metadata.account_id,
                approve=True,
            )
        governance.decide_credential(
            actor_id="owner-subject",
            tenant_id="tenant-owner",
            credential_id=metadata.account_id,
            approve=True,
        )

        session = registry.open_read_only_session(
            tenant_id="tenant-owner", account_id=metadata.account_id
        )
        try:
            assert session.get_balance()["success"] is True
            assert len(_ReadOnlyDeltaClient.instances) == 1
            assert _ReadOnlyDeltaClient.instances[0].api_key == api_key
            assert _ReadOnlyDeltaClient.instances[0].api_secret == api_secret

            # A session opened by the owner is revoked when the trusted
            # request subject changes; approval cannot be inherited by a member.
            identity.subject_id = "member-subject"
            with pytest.raises(CredentialVaultError):
                session.get_balance()
            with pytest.raises(CredentialVaultError, match="not owner-approved"):
                registry.open_read_only_session(
                    tenant_id="tenant-owner", account_id=metadata.account_id
                )
        finally:
            session.close()
        assert _ReadOnlyDeltaClient.instances[0].closed is True
    finally:
        account_repository.close()
        governance_repository.close()
