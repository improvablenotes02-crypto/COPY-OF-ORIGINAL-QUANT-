"""Phase 368: bind Delta admission to durable owner-governance records."""
import pytest

from core.accounts.delta_credential_approval import (
    OwnerGovernanceDeltaCredentialApprovalProvider,
)
from core.accounts.owner_governance import (
    OwnerGovernance,
    SQLiteOwnerGovernanceRepository,
)


def setup():
    repository = SQLiteOwnerGovernanceRepository()
    governance = OwnerGovernance(repository, owner_subject_id="owner-1", clock=lambda: 10)
    provider = OwnerGovernanceDeltaCredentialApprovalProvider(repository)
    return repository, governance, provider


def submit(governance, *, tenant="tenant-a", credential="credential-a",
           account="account-a", fingerprint="a" * 64):
    governance.submit_credential(
        actor_id="owner-1", tenant_id=tenant, credential_id=credential,
        account_id=account, fingerprint=fingerprint,
    )


def test_exact_owner_approved_tuple_is_admitted():
    repository, governance, provider = setup()
    submit(governance)
    governance.decide_credential(
        actor_id="owner-1", tenant_id="tenant-a",
        credential_id="credential-a", approve=True,
    )
    assert provider.is_approved(
        tenant_id="tenant-a", account_id="account-a", fingerprint="a" * 64
    )
    repository.close()


@pytest.mark.parametrize("tenant,account,fingerprint", [
    ("tenant-b", "account-a", "a" * 64),
    ("tenant-a", "account-b", "a" * 64),
    ("tenant-a", "account-a", "b" * 64),
])
def test_tenant_account_or_fingerprint_mismatch_is_denied(tenant, account, fingerprint):
    repository, governance, provider = setup()
    submit(governance)
    governance.decide_credential(
        actor_id="owner-1", tenant_id="tenant-a",
        credential_id="credential-a", approve=True,
    )
    assert not provider.is_approved(
        tenant_id=tenant, account_id=account, fingerprint=fingerprint
    )
    repository.close()


def test_pending_and_rejected_credentials_are_denied():
    repository, governance, provider = setup()
    submit(governance, credential="pending")
    submit(governance, credential="rejected", fingerprint="b" * 64)
    governance.decide_credential(
        actor_id="owner-1", tenant_id="tenant-a", credential_id="rejected",
        approve=False,
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="account-a", fingerprint="a" * 64
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="account-a", fingerprint="b" * 64
    )
    repository.close()


def test_revocation_and_ambiguous_duplicate_rows_fail_closed():
    repository, governance, provider = setup()
    submit(governance)
    governance.decide_credential(
        actor_id="owner-1", tenant_id="tenant-a",
        credential_id="credential-a", approve=True,
    )
    governance.revoke_credential(
        actor_id="owner-1", tenant_id="tenant-a", credential_id="credential-a"
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="account-a", fingerprint="a" * 64
    )
    submit(governance, credential="credential-b")
    governance.decide_credential(
        actor_id="owner-1", tenant_id="tenant-a",
        credential_id="credential-b", approve=True,
    )
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="account-a", fingerprint="a" * 64
    )
    repository.close()


def test_repository_failure_propagates_for_runtime_fail_closed_handling():
    repository, governance, provider = setup()
    repository.close()
    with pytest.raises(Exception):
        provider.is_approved(
            tenant_id="tenant-a", account_id="account-a", fingerprint="a" * 64
        )


def test_subject_bound_approval_only_allows_original_submitter():
    repository, governance, provider = setup()
    governance.invite_member(
        actor_id="owner-1", tenant_id="tenant-a", subject_id="member-a",
        permissions=["read"],
    )
    governance.decide_member(
        actor_id="owner-1", tenant_id="tenant-a", subject_id="member-a",
        approve=True, permissions=["read"],
    )
    governance.submit_credential(
        actor_id="member-a", tenant_id="tenant-a", credential_id="member-credential",
        account_id="account-a", fingerprint="a" * 64,
    )
    governance.decide_credential(
        actor_id="owner-1", tenant_id="tenant-a",
        credential_id="member-credential", approve=True,
    )
    assert provider.is_approved_for_subject(
        tenant_id="tenant-a", account_id="account-a",
        fingerprint="a" * 64, subject_id="member-a",
    )
    assert not provider.is_approved_for_subject(
        tenant_id="tenant-a", account_id="account-a",
        fingerprint="a" * 64, subject_id="member-b",
    )
    repository.close()


def test_provider_never_claims_production_readiness():
    repository, _governance, provider = setup()
    assert provider.production_ready is False
    repository.close()


def test_governance_adapter_is_live_runtime_admission_gate():
    from core.accounts.delta_account_registry import (
        CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry,
        SQLiteDeltaAccountRepository, delta_credential_fingerprint,
    )
    from core.accounts.delta_credential_approval import (
        OwnerGovernanceDeltaCredentialApprovalProvider,
    )

    class Crypto:
        def encrypt(self, plaintext, *, associated_data):
            import hashlib
            tag = hashlib.sha256(associated_data).digest()[:16]
            return CiphertextEnvelope("test-key", "TEST-ONLY", tag + bytes(x ^ 165 for x in plaintext))
        def decrypt(self, envelope, *, associated_data):
            import hashlib
            tag = hashlib.sha256(associated_data).digest()[:16]
            if not envelope.ciphertext.startswith(tag):
                raise ValueError("context mismatch")
            return bytes(x ^ 165 for x in envelope.ciphertext[16:])

    class Client:
        def __init__(self, **kwargs): pass
        def get_balance(self): return {"success": True}
        def close(self): pass

    governance_repo, governance, _unused = setup()
    accounts = SQLiteDeltaAccountRepository()
    try:
        fingerprint = delta_credential_fingerprint("delta-key", "delta-secret")
        meta = DeltaAccountRegistry(
            accounts, Crypto(), exchange_factory=Client,
        ).register_account(
            tenant_id="tenant-a", label="runtime", region="INDIA",
            environment="SANDBOX", api_key="delta-key", api_secret="delta-secret",
        )
        governance.submit_credential(
            actor_id="owner-1", tenant_id="tenant-a", credential_id="credential-runtime",
            account_id=meta.account_id, fingerprint=fingerprint,
        )
        provider = OwnerGovernanceDeltaCredentialApprovalProvider(governance_repo)
        registry = DeltaAccountRegistry(
            accounts, Crypto(), exchange_factory=Client,
            credential_approval_provider=provider,
        )
        with pytest.raises(CredentialVaultError, match="not owner-approved"):
            registry.open_read_only_session(tenant_id="tenant-a", account_id=meta.account_id)
        governance.decide_credential(
            actor_id="owner-1", tenant_id="tenant-a",
            credential_id="credential-runtime", approve=True,
        )
        session = registry.open_read_only_session(
            tenant_id="tenant-a", account_id=meta.account_id
        )
        assert session.get_balance() == {"success": True}
        governance.revoke_credential(
            actor_id="owner-1", tenant_id="tenant-a", credential_id="credential-runtime"
        )
        with pytest.raises(CredentialVaultError, match="no longer authorized"):
            session.get_balance()
        session.close()
    finally:
        accounts.close()
        governance_repo.close()
