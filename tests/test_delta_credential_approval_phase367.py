"""Phase 367: owner approval gates Delta credential use and sessions."""
import hashlib
import pytest
from core.accounts.delta_account_registry import CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry, SQLiteDeltaAccountRepository, delta_credential_fingerprint
class Crypto:
    def encrypt(self, plaintext, *, associated_data):
        tag=hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("test-key","TEST-ONLY",tag+bytes(x^165 for x in plaintext))
    def decrypt(self, envelope, *, associated_data):
        tag=hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag): raise ValueError("context")
        return bytes(x^165 for x in envelope.ciphertext[16:])
class Approval:
    production_ready=False
    def __init__(self, allowed=True): self.allowed=allowed; self.calls=[]
    def is_approved(self, *, tenant_id, account_id, fingerprint):
        self.calls.append((tenant_id,account_id,fingerprint)); return self.allowed
class Client:
    def __init__(self, **kwargs): pass
    def get_balance(self): return {"success":True}
    def close(self): pass
def setup(gate, factory=None):
    repo=SQLiteDeltaAccountRepository()
    registry=DeltaAccountRegistry(repo,Crypto(),exchange_factory=factory or Client,credential_approval_provider=gate)
    meta=registry.register_account(tenant_id="tenant-a",label="primary",region="INDIA",environment="SANDBOX",api_key="key-value",api_secret="secret-value")
    return registry,repo,meta
def test_approved_exact_pair_opens_session():
    gate=Approval(); registry,repo,meta=setup(gate)
    session=registry.open_read_only_session(tenant_id="tenant-a",account_id=meta.account_id)
    assert session.get_balance()=={"success":True}
    assert gate.calls[0]==("tenant-a",meta.account_id,delta_credential_fingerprint("key-value","secret-value"))
    session.close(); repo.close()
def test_denied_approval_prevents_client_construction():
    gate=Approval(False); built=[]
    def factory(**kwargs): built.append(True); return Client(**kwargs)
    registry,repo,meta=setup(gate,factory)
    with pytest.raises(CredentialVaultError,match="not owner-approved"): registry.open_read_only_session(tenant_id="tenant-a",account_id=meta.account_id)
    assert built==[]; repo.close()
def test_revocation_invalidates_existing_session():
    gate=Approval(); registry,repo,meta=setup(gate)
    session=registry.open_read_only_session(tenant_id="tenant-a",account_id=meta.account_id); gate.allowed=False
    with pytest.raises(CredentialVaultError,match="no longer authorized"): session.get_balance()
    session.close(); repo.close()
def test_approval_lookup_error_fails_closed_and_redacts():
    class Broken:
        def is_approved(self, **kwargs): raise RuntimeError("sensitive provider detail")
    registry,repo,meta=setup(Broken())
    with pytest.raises(CredentialVaultError,match="not owner-approved") as err: registry.open_read_only_session(tenant_id="tenant-a",account_id=meta.account_id)
    assert "sensitive" not in str(err.value); repo.close()
def test_fingerprint_changes_with_either_secret():
    expected=hashlib.sha256(b'{"api_key":"key","api_secret":"secret"}').hexdigest()
    assert delta_credential_fingerprint("key","secret")==expected
    assert delta_credential_fingerprint("key","secret")!=delta_credential_fingerprint("key2","secret")
    assert delta_credential_fingerprint("key","secret")!=delta_credential_fingerprint("key","secret2")
