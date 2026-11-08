"""HTTP integration tests for the OIDC-bound owner governance API."""
import json
import threading
from types import SimpleNamespace
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
from core.accounts.owner_governance_api import (
    ProductionAdmissionError,
    create_owner_governance_server,
)


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


class _AccountRegistry:
    def __init__(self):
        self.accounts = {}

    def register_account(self, *, tenant_id, label, region, environment, api_key, api_secret):
        account_id = "vault-account-1"
        self.accounts[account_id] = {
            "tenant_id": tenant_id, "label": label, "region": region,
            "environment": environment, "api_key": api_key, "api_secret": api_secret,
        }
        return SimpleNamespace(account_id=account_id)

    def delete_account(self, *, tenant_id, account_id):
        return self.accounts.pop(account_id, None) is not None


@pytest.fixture
def api(tmp_path):
    repo = SQLiteOwnerGovernanceRepository(tmp_path / "governance.sqlite")
    domain = OwnerGovernance(repo, owner_subject_id="owner-1", clock=lambda: 10)
    source = OidcTenantPrincipalSource(_Verifier(), _Membership(), clock=lambda: 1)
    facade = AuthenticatedOwnerGovernance(
        domain, source, _Sessions(), clock=lambda: 1
    )
    account_registry = _AccountRegistry()
    server = create_owner_governance_server(
        facade, allow_nonproduction=True, account_registry=account_registry
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, repo, account_registry
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


def test_request_json_rejects_duplicate_keys_and_non_finite_numbers():
    import io
    from email.message import Message
    from types import SimpleNamespace
    from core.accounts.owner_governance_api import _object_body

    def parse(raw):
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(raw))
        return _object_body(SimpleNamespace(headers=headers, rfile=io.BytesIO(raw)))

    with pytest.raises(ValueError, match="invalid JSON body"):
        parse(b'{"subject_id":"safe","subject_id":"attacker"}')
    with pytest.raises(ValueError, match="invalid JSON body"):
        parse(b'{"amount":NaN}')
    with pytest.raises(ValueError, match="invalid JSON body"):
        parse(b'{"amount":1e999}')


def test_owner_invites_and_approves_member_using_verified_actor(api):
    server, repo, *_ = api
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
    server, repo, *_ = api
    status, _ = _request(
        server, "POST", "/v1/tenants/tenant-a/members",
        "member-token", {"subject_id": "other"},
    )
    assert status == 403
    assert repo.membership("tenant-a", "other") is None


def test_credential_metadata_submission_approval_and_revocation(api):
    server, repo, *_ = api
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
    server, repo, *_ = api
    assert _request(server, "POST", "/v1/tenants/tenant-a/members",
                    None, {"subject_id": "x"})[0] == 401
    assert _request(server, "POST", "/v1/tenants/tenant-a/members",
                    "garbage", {"subject_id": "x"})[0] == 403
    assert _request(server, "POST", "/v1/tenants/tenant-b/members",
                    "owner-token", {"subject_id": "x"})[0] == 403
    assert repo.audit_events("tenant-a") == []


def test_endpoint_rejects_spoofed_actor_and_raw_api_secret(api):
    server, repo, *_ = api
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
    server, repo, *_ = api
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
    server, _repo, *_ = api
    status, _ = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/owner-1", "owner-token"
    )
    assert status == 403



def test_member_revocation_cascades_to_credentials_and_is_audited(api):
    server, repo, *_ = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1", "permissions": ["read"]})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True})
    _request(server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
             {"credential_id": "cred-member", "account_id": "acct-1",
              "fingerprint": "c" * 64})
    _request(server, "POST", "/v1/tenants/tenant-a/credentials/cred-member/decision",
             "owner-token", {"approve": True})
    status, result = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/member-1", "owner-token"
    )
    assert (status, result["status"]) == (200, "REVOKED")
    assert repo.membership("tenant-a", "member-1").status == "REVOKED"
    assert repo.credential("tenant-a", "cred-member").status == "REVOKED"
    actions = [event["action"] for event in repo.audit_events("tenant-a")]
    assert "MEMBER_REVOKED" in actions
    assert "CREDENTIAL_REVOKED_MEMBER_REMOVAL" in actions


def test_nonproduction_composition_requires_explicit_opt_in(tmp_path):
    repo = SQLiteOwnerGovernanceRepository(tmp_path / "local.sqlite")
    domain = OwnerGovernance(repo, owner_subject_id="owner-1")
    facade = AuthenticatedOwnerGovernance(
        domain, OidcTenantPrincipalSource(_Verifier(), _Membership()),
        _Sessions(),
    )
    with pytest.raises(ProductionAdmissionError, match="not production-admissible"):
        create_owner_governance_server(facade)
    repo.close()

def test_owner_can_list_members_and_pending_credential_approvals(api):
    server, repo, *_ = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1", "permissions": ["read"]})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True, "permissions": ["read"]})
    _request(server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
             {"credential_id": "cred-pending", "account_id": "acct-1", "fingerprint": "d" * 64})
    status, members = _request(server, "GET", "/v1/tenants/tenant-a/members", "owner-token")
    assert status == 200 and members["members"][0]["subject_id"] == "member-1"
    status, credentials = _request(server, "GET", "/v1/tenants/tenant-a/credentials", "owner-token")
    assert status == 200 and credentials["credentials"][0]["status"] == "PENDING"
    assert credentials["credentials"][0]["account_id"] == "acct-1"
    assert "fingerprint" not in credentials["credentials"][0]

def test_member_cannot_list_owner_management_views(api):
    server, repo, *_ = api
    _request(server, "POST", "/v1/tenants/tenant-a/members", "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision", "owner-token", {"approve": True})
    assert _request(server, "GET", "/v1/tenants/tenant-a/members", "member-token")[0] == 403
    assert _request(server, "GET", "/v1/tenants/tenant-a/credentials", "member-token")[0] == 403

def test_member_submits_raw_delta_credentials_to_encrypted_registry_for_owner_approval(api):
    server, repo, registry = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True})
    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
        {"label": "My Delta account", "region": "global",
         "environment": "testnet", "api_key": "private-api-key",
         "api_secret": "private-api-secret"},
    )
    assert status == 200
    assert result == {"ok": True, "account_id": "vault-account-1", "status": "PENDING"}
    assert "private-api-key" not in json.dumps(result)
    assert "private-api-secret" not in json.dumps(result)
    assert registry.accounts["vault-account-1"]["api_secret"] == "private-api-secret"
    approval = repo.credential("tenant-a", "vault-account-1")
    assert approval.status == "PENDING"
    assert approval.account_id == "vault-account-1"


def test_owner_credential_revocation_deletes_encrypted_vault_record(api):
    server, repo, registry = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True})
    status, submitted = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
        {"label": "Trading account", "region": "global", "environment": "testnet",
         "api_key": "revoke-key", "api_secret": "revoke-secret"},
    )
    assert status == 200 and submitted["status"] == "PENDING"
    account_id = submitted["account_id"]
    assert account_id in registry.accounts
    status, approved = _request(
        server, "POST", f"/v1/tenants/tenant-a/credentials/{account_id}/decision",
        "owner-token", {"approve": True},
    )
    assert status == 200 and approved["status"] == "APPROVED"

    status, revoked = _request(
        server, "DELETE", f"/v1/tenants/tenant-a/credentials/{account_id}",
        "owner-token",
    )
    assert status == 200
    assert revoked == {"ok": True, "status": "REVOKED", "vault_deleted": True}
    assert repo.credential("tenant-a", account_id).status == "REVOKED"
    assert account_id not in registry.accounts

    # A retry safely completes cleanup if the first delete failed after revocation.
    status, repeated = _request(
        server, "DELETE", f"/v1/tenants/tenant-a/credentials/{account_id}",
        "owner-token",
    )
    assert status == 200 and repeated["status"] == "REVOKED"


def test_member_revocation_deletes_all_submitted_vault_credentials(api):
    server, repo, registry = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True})
    status, submitted = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
        {"label": "Member trading account", "region": "global",
         "environment": "testnet", "api_key": "member-key",
         "api_secret": "member-secret"},
    )
    assert status == 200
    account_id = submitted["account_id"]
    assert account_id in registry.accounts

    status, result = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/member-1", "owner-token"
    )
    assert status == 200
    assert result["status"] == "REVOKED"
    assert result["vault_deleted"] == 1
    assert result["vault_cleanup_pending"] == 0
    assert repo.membership("tenant-a", "member-1").status == "REVOKED"
    assert repo.credential("tenant-a", account_id).status == "REVOKED"
    assert account_id not in registry.accounts


def test_raw_credential_submission_rolls_back_vault_record_when_membership_not_approved(api):
    server, _repo, registry = api
    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
        {"label": "My Delta account", "region": "global",
         "environment": "testnet", "api_key": "private-api-key",
         "api_secret": "private-api-secret"},
    )
    assert status == 403
    assert result == {"error": "forbidden"}
    assert registry.accounts == {}


def test_member_revocation_reports_and_allows_retry_of_failed_vault_cleanup(api):
    server, repo, registry = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True})
    status, submitted = _request(
        server, "POST", "/v1/tenants/tenant-a/credentials", "member-token",
        {"label": "Retry cleanup", "region": "global", "environment": "testnet",
         "api_key": "cleanup-key", "api_secret": "cleanup-secret"},
    )
    assert status == 200
    account_id = submitted["account_id"]
    original_delete = registry.delete_account
    attempts = []

    def fail_once(*, tenant_id, account_id):
        attempts.append(account_id)
        if len(attempts) == 1:
            raise OSError("temporary vault outage")
        return original_delete(tenant_id=tenant_id, account_id=account_id)

    registry.delete_account = fail_once
    status, result = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/member-1", "owner-token"
    )
    assert status == 200
    assert result["status"] == "REVOKED"
    assert result["vault_deleted"] == 0
    assert result["vault_cleanup_pending"] == 1
    assert repo.membership("tenant-a", "member-1").status == "REVOKED"
    assert repo.credential("tenant-a", account_id).status == "REVOKED"
    assert account_id in registry.accounts

    # The owner can locate the revoked record and retry its idempotent cleanup.
    status, queue = _request(
        server, "GET", "/v1/tenants/tenant-a/credentials", "owner-token"
    )
    assert status == 200
    credential = next(item for item in queue["credentials"]
                      if item["account_id"] == account_id)
    assert credential["status"] == "REVOKED"
    status, cleanup = _request(
        server, "DELETE",
        f"/v1/tenants/tenant-a/credentials/{credential['credential_id']}",
        "owner-token",
    )
    assert status == 200
    assert cleanup["status"] == "REVOKED"
    assert cleanup["vault_deleted"] is True
    assert account_id not in registry.accounts
    assert attempts == [account_id, account_id]


@pytest.mark.parametrize("permissions", [
    None, "read", {"read": True}, [None], [["read"]], [1], ["unknown"],
])
def test_owner_member_permissions_reject_malformed_values_without_mutation(api, permissions):
    server, repo, _registry = api
    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/members", "owner-token",
        {"subject_id": "member-invalid-permissions", "permissions": permissions},
    )
    assert status == 400
    assert result["error"] == "bad_request"
    assert repo.membership("tenant-a", "member-invalid-permissions") is None


def test_owner_member_permissions_accept_supported_values_and_deduplicate(api):
    server, repo, _registry = api
    status, result = _request(
        server, "POST", "/v1/tenants/tenant-a/members", "owner-token",
        {"subject_id": "member-valid-permissions",
         "permissions": ["read", "trade_paper", "read"]},
    )
    assert status == 200
    assert result["status"] == "PENDING"
    member = repo.membership("tenant-a", "member-valid-permissions")
    assert member.permissions == ("read", "trade_paper")


def test_get_and_delete_reject_request_bodies(api):
    server, repo, *_ = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1"})
    status, result = _request(
        server, "DELETE", "/v1/tenants/tenant-a/members/member-1",
        "owner-token", {"unexpected": "ignored-before-fix"},
    )
    assert status == 400
    assert result["error"] == "bad_request"
    assert repo.membership("tenant-a", "member-1").status == "PENDING"

    status, result = _request(
        server, "GET", "/v1/tenants/tenant-a/members",
        "owner-token", {"unexpected": "ignored-before-fix"},
    )
    assert status == 400
    assert result["error"] == "bad_request"


@pytest.mark.parametrize("field,value", [
    ("api_key", 123),
    ("api_secret", None),
    ("label", ["account"]),
    ("region", {"name": "global"}),
    ("environment", False),
    ("api_key", "   "),
    ("api_secret", ""),
    ("label", ""),
])
def test_raw_credential_submission_rejects_invalid_field_types_before_vault_write(api, field, value):
    server, _repo, registry = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True})
    payload = {"label": "Trading account", "region": "global",
               "environment": "testnet", "api_key": "valid-key",
               "api_secret": "valid-secret"}
    payload[field] = value
    status, result = _request(server, "POST", "/v1/tenants/tenant-a/credentials",
                              "member-token", payload)
    assert status == 400
    assert result["error"] == "bad_request"
    assert registry.accounts == {}


@pytest.mark.parametrize("field,maximum", [
    ("api_key", 4096),
    ("api_secret", 4096),
    ("label", 80),
    ("region", 32),
    ("environment", 32),
])
def test_raw_credential_submission_enforces_field_size_limits_before_vault_write(api, field, maximum):
    server, _repo, registry = api
    _request(server, "POST", "/v1/tenants/tenant-a/members",
             "owner-token", {"subject_id": "member-1"})
    _request(server, "POST", "/v1/tenants/tenant-a/members/member-1/decision",
             "owner-token", {"approve": True})
    payload = {"label": "Trading account", "region": "global",
               "environment": "testnet", "api_key": "valid-key",
               "api_secret": "valid-secret"}
    payload[field] = "x" * (maximum + 1)
    status, result = _request(server, "POST", "/v1/tenants/tenant-a/credentials",
                              "member-token", payload)
    assert status == 400
    assert result["error"] == "bad_request"
    assert registry.accounts == {}
