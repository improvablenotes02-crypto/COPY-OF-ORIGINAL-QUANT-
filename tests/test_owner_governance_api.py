"""HTTP integration tests for the OIDC-bound owner governance API."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from core.accounts.oidc_tenant_principal import (
    OidcTenantPrincipalSource,
    VerifiedAccessToken,
)
from core.accounts.owner_governance import (
    AuthenticatedOwnerGovernance,
    OwnerGovernance,
    SQLiteOwnerGovernanceRepository,
)
from core.accounts.owner_governance_api import create_owner_governance_server


class _Verifier:
    production_ready = True

    def verify_access_token(self, token):
        subjects = {"owner-token": "owner-1", "member-token": "member-1"}
        if token not in subjects:
            raise ValueError("invalid token")
        return VerifiedAccessToken(subjects[token], "session-" + subjects[token], 9999)


class _Membership:
    production_ready = True

    def tenant_ids_for_subject(self, subject):
        return frozenset({"tenant-a"})


class _Sessions:
    production_ready = True

    def is_session_active(self, principal):
        return principal.session_id in {"session-owner-1", "session-member-1"}


@pytest.fixture
def api(tmp_path):
    repo = SQLiteOwnerGovernanceRepository(tmp_path / "governance.sqlite")
    domain = OwnerGovernance(repo, owner_subject_id="owner-1", clock=lambda: 10)
    source = OidcTenantPrincipalSource(_Verifier(), _Membership(), clock=lambda: 1)
    facade = AuthenticatedOwnerGovernance(
        domain, source, _Sessions(), clock=lambda: 1
    )
    server = create_owner_governance_server(facade)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, repo
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        repo.close()


def _request(server, method, path, token=None, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}",
        data=data, headers=headers, method=method,
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_owner_invites_and_approves_member_using_verified_actor(api):
    server, repo = api
    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/members",
        "owner-token", {"subject_id": "member-1", "permissions": ["read"]},
    )
    assert (status, result["status"]) == (200, "PENDING")
    assert repo.membership("tenant-a", "member-1").status == "PENDING"

    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
        "owner-token", {"approve": True, "permissions": ["read", "trade_paper"]},
    )
    assert (status, result["status"]) == (200, "APPROVED")
    assert repo.membership("tenant-a", "member-1").permissions == ("read", "trade_paper")


def test_member_cannot_invite_or_approve_another_member(api):
    server, repo = api
    status, _ = _request(
        server, "POST", "/v1/tenants/tenant-a/members",
        "member-token", {"subject_id": "other"},
    )
    assert status == 403
    assert repo.membership("tenant-a", "other") is None


def test_credential_metadata_submission_approval_and_revocation(api):
    server, repo = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
              "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
              "owner-token", {"approve": True})
    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
        {"credential_id": "cred-1", "account_id": "acct-1", "fingerprint": "a" * 64},
    )
    assert (status, result["status"]) == (200, "PENDING")
    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials/cred-1/decision",
        "owner-token", {"approve": True},
    )
    assert (status, result["status"]) == (200, "APPROVED")
    status, result = _request(
        server, "DELETE", "/v1/tenants/tenant-a/credentials/cred-1", "owner-token",
    )
    assert (status, result["status"]) == (200, "REVOKED")
    assert repo.credential("tenant-a", "cred-1").status == "REVOKED"


def test_missing_invalid_token_and_tenant_mismatch_fail_closed(api):
    server, repo = api
    assert _request(server, "POST", "/v1/tenants/tenant-a/members",
                    None, {"subject_id": "x"})[0] == 401
    assert _request(server, "POST", "/v1/tenants/tenant-a/members",
                    "garbage", {"subject_id": "x"})[0] == 403
    assert _request(server, "POST", "/v1/tenants/tenant-b/members",
                    "owner-token", {"subject_id": "x"})[0] == 403
    assert repo.audit_events("tenant-a") == []


def test_endpoint_rejects_spoofed_actor_and_raw_api_secret(api):
    server, repo = api
    status, _ = _request(
        server, "POST", "/v1/tenants/tenant-a/members", "owner-token",
        {"subject_id": "x", "actor_id": "owner-1"},
    )
    assert status == 400
    status, _ = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials", "owner-token",
        {"credential_id": "c", "account_id": "a", "fingerprint": "a" * 64,
         "api_key": "must-never-be-accepted"},
    )
    assert status == 400
    assert repo.audit_events("tenant-a") == []


def test_server_refuses_non_loopback_binding():
    with pytest.raises(ValueError, match="loopback"):
        create_owner_governance_server(object(), host="0.0.0.0")


def test_owner_can_revoke_member_and_clear_permissions(api):
    server, repo = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
              "owner-token", {"subject_id": "member-1", "permissions": ["read", "trade_paper"]})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
              "owner-token", {"approve": True, "permissions": ["read", "trade_paper"]})
    _request(server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
             {"credential_id": "cred-revoke", "account_id": "acct-revoke",
              "fingerprint": "f" * 64})
    _request(server, "POST", "/v1/tenants/tenant-a/credentials/cred-revoke/decision",
             "owner-token", {"approve": True})

    status, _ = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/member-1", "member-token"
    )
    assert status == 403
    assert repo.membership("tenant-a", "member-1").status == "APPROVED"

    status, result = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/member-1", "owner-token"
    )
    assert (status, result["status"]) == (200, "REVOKED")
    membership = repo.membership("tenant-a", "member-1")
    assert membership.status == "REVOKED"
    assert membership.permissions == ()
    assert repo.credential("tenant-a", "cred-revoke").status == "REVOKED"
    from core.accounts.delta_credential_approval import OwnerGovernanceDeltaCredentialApprovalProvider
    provider = OwnerGovernanceDeltaCredentialApprovalProvider(repo)
    assert not provider.is_approved(
        tenant_id="tenant-a", account_id="acct-revoke", fingerprint="f" * 64
    )
    actions = [event["action"] for event in repo.audit_events("tenant-a")]
    assert "CREDENTIAL_REVOKED_MEMBER_REMOVAL" in actions
    assert "MEMBER_REVOKED" in actions


def test_owner_cannot_revoke_own_identity(api):
    server, _repo = api
    status, _ = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/owner-1", "owner-token"
    )
    assert status == 403
