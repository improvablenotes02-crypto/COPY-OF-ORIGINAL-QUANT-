"""Phase 363: verified OIDC claims and server-side tenant membership."""
import pytest

from core.accounts.oidc_tenant_principal import (
    OidcTenantPrincipalSource, VerifiedAccessToken, bind_access_token,
)


class _Verifier:
    production_ready = True
    def __init__(self):
        self.error = False
        self.tokens = []
    def verify_access_token(self, token):
        self.tokens.append(token)
        if self.error:
            raise RuntimeError("signature or issuer details must not escape")
        return VerifiedAccessToken("subject-1", "session-1", 500.0)


class _Membership:
    production_ready = True
    def __init__(self):
        self.calls = []
        self.result = frozenset({"tenant-server-authorized"})
        self.error = False
    def tenant_ids_for_subject(self, subject_id):
        self.calls.append(subject_id)
        if self.error:
            raise RuntimeError("database connection string must not escape")
        return self.result


def _source(now=100.0):
    verifier, membership = _Verifier(), _Membership()
    return OidcTenantPrincipalSource(
        verifier, membership, clock=lambda: now
    ), verifier, membership


def test_principal_uses_verified_identity_and_server_side_membership():
    source, verifier, membership = _source()
    with bind_access_token("opaque-test-token"):
        principal = source.current_principal()
    assert principal.subject_id == "subject-1"
    assert principal.session_id == "session-1"
    assert principal.tenant_ids == frozenset({"tenant-server-authorized"})
    assert verifier.tokens == ["opaque-test-token"]
    assert membership.calls == ["subject-1"]


def test_missing_token_has_no_principal_and_does_not_call_providers():
    source, verifier, membership = _source()
    assert source.current_principal() is None
    assert verifier.tokens == []
    assert membership.calls == []


def test_verifier_failure_is_redacted_and_denies():
    source, verifier, _ = _source()
    verifier.error = True
    with bind_access_token("invalid-token"):
        with pytest.raises(PermissionError, match="principal unavailable") as caught:
            source.current_principal()
    assert "signature or issuer" not in str(caught.value)


def test_membership_failure_is_redacted_and_denies():
    source, _, membership = _source()
    membership.error = True
    with bind_access_token("valid-token"):
        with pytest.raises(PermissionError, match="principal unavailable") as caught:
            source.current_principal()
    assert "connection string" not in str(caught.value)


def test_expired_claims_are_rejected_before_membership_lookup():
    source, _, membership = _source(now=500.0)
    with bind_access_token("expired-token"):
        with pytest.raises(PermissionError):
            source.current_principal()
    assert membership.calls == []


def test_token_cannot_supply_tenant_membership():
    source, _, membership = _source()
    membership.result = frozenset({"tenant-from-database"})
    with bind_access_token("token-claim-tenant-attacker-choice"):
        principal = source.current_principal()
    assert principal.tenant_ids == frozenset({"tenant-from-database"})
    assert "attacker-choice" not in principal.tenant_ids


def test_malformed_membership_result_fails_closed():
    source, _, membership = _source()
    membership.result = {"tenant-untrusted"}
    with bind_access_token("valid-token"):
        with pytest.raises(PermissionError):
            source.current_principal()


def test_production_readiness_requires_both_provider_admissions():
    source, verifier, membership = _source()
    assert source.production_ready is True
    verifier.production_ready = False
    assert source.production_ready is False
    verifier.production_ready = True
    membership.production_ready = False
    assert source.production_ready is False


def test_access_token_context_is_restored_after_exception():
    source, _, _ = _source()
    with pytest.raises(RuntimeError):
        with bind_access_token("outer-token"):
            with bind_access_token("inner-token"):
                raise RuntimeError("request aborted")
    assert source.current_principal() is None
