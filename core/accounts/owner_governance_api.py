"""Loopback HTTP API for owner-governed membership and credential approval.

Every mutation is authenticated with a verified OIDC bearer token. The token is
bound only for the lifetime of one request; actor identity and tenant membership
come from OidcTenantPrincipalSource and its authoritative membership resolver.
No route accepts actor IDs, roles, API keys, or API secrets from the caller.
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from core.accounts.oidc_tenant_principal import bind_access_token
from core.accounts.owner_governance import (
    GovernanceConflictError,
    OwnerAuthorizationError,
)


_MAX_BODY_BYTES = 16 * 1024
_SEGMENT = re.compile(r"^[A-Za-z0-9_.:@+-]{1,160}$")


def _segment(value: str) -> str:
    decoded = unquote(value)
    if not _SEGMENT.fullmatch(decoded) or decoded in {".", ".."}:
        raise ValueError("invalid path identifier")
    return decoded


def _object_body(handler) -> dict:
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        raise ValueError("Content-Length is required")
    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        raise ValueError("invalid Content-Length") from None
    if length < 0 or length > _MAX_BODY_BYTES:
        raise ValueError("request body exceeds limit")
    if handler.headers.get("Transfer-Encoding"):
        raise ValueError("transfer encoding is not supported")
    if handler.headers.get_content_type() != "application/json":
        raise ValueError("application/json is required")
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ValueError("incomplete request body")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid JSON body") from None
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def _only_fields(body: dict, required: set[str], optional: set[str] = frozenset()):
    if not required.issubset(body) or set(body) - required - set(optional):
        raise ValueError("request fields do not match endpoint contract")


def _bearer(handler) -> str:
    header = handler.headers.get("Authorization", "")
    scheme, separator, value = header.partition(" ")
    if not separator or scheme.lower() != "bearer" or not value.strip():
        raise PermissionError("verified bearer token required")
    return value.strip()


def _dispatch(governance, method: str, path: str, body: dict):
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3 or parts[:2] != ["v1", "tenants"]:
        raise LookupError("route not found")
    tenant = _segment(parts[2])

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

    if method == "POST" and len(parts) == 4 and parts[3] == "credentials":
        _only_fields(body, {"credential_id", "account_id", "fingerprint"})
        governance.submit_credential(
            tenant_id=tenant,
            credential_id=body["credential_id"],
            account_id=body["account_id"],
            fingerprint=body["fingerprint"],
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
        governance.revoke_credential(
            tenant_id=tenant, credential_id=_segment(parts[4])
        )
        return {"ok": True, "status": "REVOKED"}

    raise LookupError("route not found")


def create_owner_governance_server(
    governance,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
):
    """Create a loopback-only server; caller owns lifecycle and OIDC adapters."""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("owner governance API must bind to loopback")
    if governance is None:
        raise ValueError("authenticated owner governance facade is required")

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
                body = _object_body(self) if method == "POST" else {}
                with bind_access_token(token):
                    result = _dispatch(governance, method, path, body)
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

        def log_message(self, *_args):
            pass

    return ThreadingHTTPServer((host, int(port)), Handler)
