"""Phase 309: revalidate the request subject after a slow venue identity probe."""
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from core.accounts.delta_account_registry import CiphertextEnvelope, CredentialVaultError, DeltaAccountRegistry, SQLiteDeltaAccountRepository

class _Encryption:
    def encrypt(self, plaintext, *, associated_data):
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("test-only-key", "TEST-ONLY-XOR", tag + bytes(value ^ 0xA5 for value in plaintext))
    def decrypt(self, envelope, *, associated_data):
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag): raise ValueError("associated data mismatch")
        return bytes(value ^ 0xA5 for value in envelope.ciphertext[16:])

class _Identity:
    production_ready = False
    def __init__(self): self.subject_id = "owner-subject"
    def authorize_tenant(self, tenant_id): return tenant_id == "tenant-owner"
    def current_subject_id(self, tenant_id):
        if not self.authorize_tenant(tenant_id): raise PermissionError("tenant denied")
        return self.subject_id

class _Approval:
    production_ready = False
    def is_approved(self, **kwargs): return False
    def is_approved_for_subject(self, *, subject_id, **kwargs): return subject_id == "owner-subject"

class _PausedProbe:
    def __init__(self, entered, release): self.entered, self.release, self.closed = entered, release, False
    def _get_authenticated_account_id(self):
        self.entered.set()
        if not self.release.wait(timeout=10): raise TimeoutError("test did not release identity probe")
        return "123456"
    def close(self): self.closed = True

def test_subject_change_during_identity_probe_prevents_provider_identity_binding():
    repository = SQLiteDeltaAccountRepository()
    identity = _Identity()
    entered, release, probes = threading.Event(), threading.Event(), []
    def exchange_factory(*, api_key, api_secret, base_url):
        probe = _PausedProbe(entered, release)
        probes.append(probe)
        return probe
    registry = DeltaAccountRegistry(repository, _Encryption(), exchange_factory=exchange_factory, tenant_authorizer=identity, credential_approval_provider=_Approval())
    try:
        account = registry.register_account(tenant_id="tenant-owner", label="Owner Delta", region="INDIA", environment="SANDBOX", api_key="owner-key", api_secret="owner-secret")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(registry.verify_and_bind_identity, tenant_id="tenant-owner", account_id=account.account_id)
            assert entered.wait(timeout=10), "identity probe did not start"
            identity.subject_id = "member-subject"
            release.set()
            with pytest.raises(CredentialVaultError, match="no longer authorized"): future.result(timeout=15)
        persisted = repository.get("tenant-owner", account.account_id)
        assert persisted is not None and persisted.provider_account_id is None
        assert probes and probes[0].closed is True
    finally:
        release.set()
        repository.close()
