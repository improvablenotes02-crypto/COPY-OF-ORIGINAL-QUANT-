"""Loopback HTTP API for owner-governed membership and credential approval.

Every mutation is authenticated with a verified OIDC bearer token. The token is
bound only for the lifetime of one request; actor identity and tenant membership
come from OidcTenantPrincipalSource and its authoritative membership resolver.
No route accepts actor IDs, roles, API keys, or API secrets from the caller.
"""
from __future__ import annotations

import ipaddress
import json
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from core.accounts.oidc_tenant_principal import bind_access_token
from core.accounts.delta_account_registry import delta_credential_fingerprint
from core.accounts.owner_governance import (
    GovernanceConflictError,
    OwnerAuthorizationError,
)


_MAX_BODY_BYTES = 16 * 1024


class ProductionAdmissionError(RuntimeError):
    """The governance composition is not certified for production admission."""
_SEGMENT = re.compile(r"^[A-Za-z0-9_.:@+-]{1,160}$")


def _segment(value: str) -> str:
    decoded = unquote(value)
    if not _SEGMENT.fullmatch(decoded) or decoded in {".", ".."}:
        raise ValueError("invalid path identifier")
    return decoded


def _content_length(handler, *, required: bool) -> int | None:
    values = handler.headers.get_all("Content-Length", [])
    if len(values) > 1:
        raise ValueError("duplicate Content-Length is not supported")
    if not values:
        if required:
            raise ValueError("Content-Length is required")
        return None
    raw_length = values[0]
    if not re.fullmatch(r"[0-9]+", raw_length):
        raise ValueError("invalid Content-Length")
    try:
        return int(raw_length)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid Content-Length") from None


def _reject_transfer_encoding(handler) -> None:
    if handler.headers.get_all("Transfer-Encoding", []):
        raise ValueError("transfer encoding is not supported")


def _object_body(handler) -> dict:
    length = _content_length(handler, required=True)
    if length < 0 or length > _MAX_BODY_BYTES:
        raise ValueError("request body exceeds limit")
    _reject_transfer_encoding(handler)
    content_types = handler.headers.get_all("Content-Type", [])
    if len(content_types) != 1:
        raise ValueError("exactly one Content-Type header is required")
    if handler.headers.get_content_type() != "application/json":
        raise ValueError("application/json is required")
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ValueError("incomplete request body")
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number

    def reject_constant(_value):
        raise ValueError("non-standard JSON numeric constant")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_float=finite_float,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("invalid JSON body") from None
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def _only_fields(body: dict, required: set[str], optional: set[str] = frozenset()):
    if not required.issubset(body) or set(body) - required - set(optional):
        raise ValueError("request fields do not match endpoint contract")


def _empty_body(handler) -> dict:
    """Reject bodies on GET/DELETE so ignored bytes cannot hide extra input."""
    _reject_transfer_encoding(handler)
    length = _content_length(handler, required=False)
    if length is not None and length != 0:
        raise ValueError("request body must be empty")
    return {}


def _bearer(handler) -> str:
    values = handler.headers.get_all("Authorization", [])
    if len(values) != 1:
        raise PermissionError("exactly one bearer authorization header required")
    header = values[0]
    match = re.fullmatch(r"(?i:Bearer) +([A-Za-z0-9._~+/-]+=*)", header)
    if match is None:
        raise PermissionError("verified bearer token required")
    return match.group(1)


def _dispatch(governance, method: str, path: str, body: dict, account_registry=None):
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3 or parts[:2] != ["v1", "tenants"]:
        raise LookupError("route not found")
    tenant = _segment(parts[2])

    if method == "GET" and len(parts) == 4 and parts[3] == "members":
        members = governance.list_members(tenant_id=tenant)
        return {"members": [
            {"subject_id": item.subject_id, "status": item.status,
             "permissions": list(item.permissions), "created_at_ns": item.created_at_ns,
             "updated_at_ns": item.updated_at_ns}
            for item in members
        ]}

    if method == "GET" and len(parts) == 4 and parts[3] == "credentials":
        credentials = governance.list_credentials(tenant_id=tenant)
        return {"credentials": [
            {"credential_id": item.credential_id, "subject_id": item.subject_id,
             "account_id": item.account_id,
             "status": item.status, "created_at_ns": item.created_at_ns,
             "updated_at_ns": item.updated_at_ns}
            for item in credentials
        ]}

    if method == "POST" and len(parts) == 4 and parts[3] == "members":
        _only_fields(body, {"subject_id"}, {"permissions"})
        governance.invite_member(
            tenant_id=tenant,
            subject_id=body["subject_id"],
            permissions=body.get("permissions", ()),
        )
        return {"ok": True, "status": "PENDING"}

    if method == "POST" and len(parts) == 6 and parts[3] == "members" and parts[5] == "decision":
        _only_fields(body, {"approve"}, {"permissions"})
        governance.decide_member(
            tenant_id=tenant,
            subject_id=_segment(parts[4]),
            approve=body["approve"],
            permissions=body.get("permissions", ()),
        )
        return {"ok": True, "status": "APPROVED" if body["approve"] else "REJECTED"}

    if method == "DELETE" and len(parts) == 5 and parts[3] == "members":
        if body:
            raise ValueError("DELETE request body must be empty")
        subject_id = _segment(parts[4])
        member_credentials = [
            item for item in governance.list_credentials(tenant_id=tenant)
            if item.subject_id == subject_id
        ]
        governance.revoke_member(tenant_id=tenant, subject_id=subject_id)
        vault_deleted = 0
        vault_cleanup_pending = 0
        if account_registry is not None:
            for item in member_credentials:
                try:
                    if account_registry.delete_account(
                        tenant_id=tenant, account_id=item.account_id
                    ):
                        vault_deleted += 1
                except Exception:
                    # Membership and credential approval are already revoked;
                    # a failed vault cleanup cannot restore access.
                    vault_cleanup_pending += 1
        return {
            "ok": True, "status": "REVOKED",
            "vault_deleted": vault_deleted,
            "vault_cleanup_pending": vault_cleanup_pending,
        }

    if method == "POST" and len(parts) == 4 and parts[3] == "credentials":
        if {"api_key", "api_secret", "label", "region", "environment"} == set(body):
            if account_registry is None:
                raise LookupError("credential submission is not configured")
            # Validate untrusted JSON types before hashing or passing values to
            # the vault. This keeps malformed submissions on the 400 boundary.
            for field in ("api_key", "api_secret", "label", "region", "environment"):
                value = body[field]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{field} must be a non-empty string")
            fingerprint = delta_credential_fingerprint(body["api_key"], body["api_secret"])
            metadata = account_registry.register_account(
                tenant_id=tenant, label=body["label"], region=body["region"],
                environment=body["environment"], api_key=body["api_key"],
                api_secret=body["api_secret"],
            )
            account_id = metadata.account_id
            try:
                governance.submit_credential(
                    tenant_id=tenant, credential_id=account_id,
                    account_id=account_id, fingerprint=fingerprint,
                )
            except Exception:
                try:
                    account_registry.delete_account(tenant_id=tenant, account_id=account_id)
                except Exception:
                    pass
                raise
            return {"ok": True, "account_id": account_id, "status": "PENDING"}
        _only_fields(body, {"credential_id", "account_id", "fingerprint"})
        governance.submit_credential(
            tenant_id=tenant, credential_id=body["credential_id"],
            account_id=body["account_id"], fingerprint=body["fingerprint"],
        )
        return {"ok": True, "status": "PENDING"}

    if method == "POST" and len(parts) == 6 and parts[3] == "credentials" and parts[5] == "decision":
        _only_fields(body, {"approve"})
        credential_id = _segment(parts[4])
        governance.decide_credential(
            tenant_id=tenant, credential_id=credential_id, approve=body["approve"]
        )
        return {"ok": True, "status": "APPROVED" if body["approve"] else "REJECTED"}

    if method == "DELETE" and len(parts) == 5 and parts[3] == "credentials":
        if body:
            raise ValueError("DELETE request body must be empty")
        credential_id = _segment(parts[4])
        # Revoke approval first so the credential becomes unusable immediately.
        # If vault deletion later fails, a repeated DELETE can finish cleanup.
        records = governance.list_credentials(tenant_id=tenant)
        record = next((item for item in records if item.credential_id == credential_id), None)
        if record is None:
            raise LookupError("credential not found")
        if record.status == "APPROVED":
            governance.revoke_credential(
                tenant_id=tenant, credential_id=credential_id
            )
        elif record.status != "REVOKED":
            raise GovernanceConflictError("credential is not approved")
        vault_deleted = False
        if account_registry is not None:
            vault_deleted = account_registry.delete_account(
                tenant_id=tenant, account_id=record.account_id
            )
        return {"ok": True, "status": "REVOKED", "vault_deleted": vault_deleted}

    raise LookupError("route not found")



class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a hard cap on active handlers."""

    daemon_threads = True
    _OVERLOAD_RESPONSE = (
        b"HTTP/1.1 503 Service Unavailable\r\n"
        b"Connection: close\r\n"
        b"Content-Length: 0\r\n"
        b"Retry-After: 1\r\n\r\n"
    )

    def __init__(self, address, handler, *, max_workers: int, request_timeout: float):
        self._request_slots = threading.BoundedSemaphore(max_workers)
        self._request_timeout = request_timeout
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            try:
                request.sendall(self._OVERLOAD_RESPONSE)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            request.settimeout(self._request_timeout)
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def create_owner_governance_server(
    governance,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    max_workers: int = 16,
    request_timeout: float = 10.0,
    allow_nonproduction: bool = False,
    account_registry=None,
):
    """Create a bounded loopback server; caller owns lifecycle and OIDC adapters."""
    if not isinstance(host, str) or host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("owner governance API must bind to loopback")
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or not 1 <= max_workers <= 128:
        raise ValueError("max_workers must be an integer from 1 to 128")
    if isinstance(request_timeout, bool) or not isinstance(request_timeout, (int, float)):
        raise ValueError("request_timeout must be finite and in (0, 120] seconds")
    try:
        timeout_value = float(request_timeout)
    except (OverflowError, ValueError):
        raise ValueError("request_timeout must be finite and in (0, 120] seconds") from None
    if not math.isfinite(timeout_value) or not 0 < timeout_value <= 120:
        raise ValueError("request_timeout must be finite and in (0, 120] seconds")
    if governance is None:
        raise ValueError("authenticated owner governance facade is required")
    if not isinstance(allow_nonproduction, bool):
        raise ValueError("allow_nonproduction must be boolean")
    if getattr(governance, "production_ready", False) is not True and not allow_nonproduction:
        raise ProductionAdmissionError(
            "owner governance composition is not production-admissible"
        )

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, status: int, payload: dict):
            data = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def _handle(self, method: str):
            try:
                token = _bearer(self)
                path = urlsplit(self.path).path
                body = _object_body(self) if method == "POST" else _empty_body(self)
                with bind_access_token(token):
                    result = _dispatch(governance, method, path, body, account_registry)
                self._reply(200, result)
            except PermissionError:
                self._reply(401, {"error": "unauthorized"})
            except OwnerAuthorizationError:
                self._reply(403, {"error": "forbidden"})
            except GovernanceConflictError:
                self._reply(409, {"error": "state_conflict"})
            except ValueError as exc:
                self._reply(400, {"error": "bad_request", "detail": str(exc)[:160]})
            except LookupError:
                self._reply(404, {"error": "not_found"})
            except Exception:
                # Do not echo verifier, persistence, token, or credential errors.
                self._reply(500, {"error": "internal_error"})

        def do_POST(self):
            self._handle("POST")

        def do_DELETE(self):
            self._handle("DELETE")

        def do_GET(self):
            self._handle("GET")

        def log_message(self, *_args):
            pass

    server = _BoundedThreadingHTTPServer(
        (host, int(port)),
        Handler,
        max_workers=max_workers,
        request_timeout=timeout_value,
    )
    try:
        bound_address = ipaddress.ip_address(server.server_address[0].split("%", 1)[0])
    except ValueError:
        server.server_close()
        raise ValueError("resolved bind address must be a numeric loopback address") from None
    if not bound_address.is_loopback:
        server.server_close()
        raise ValueError("resolved bind address must be loopback")
    return server
