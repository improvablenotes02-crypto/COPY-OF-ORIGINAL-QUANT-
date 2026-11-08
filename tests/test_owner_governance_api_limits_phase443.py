"""Adversarial resource-boundary tests for the owner governance HTTP API."""
import ipaddress
import socket
import threading
import time
from urllib.request import Request, urlopen

import pytest

from core.accounts.owner_governance_api import create_owner_governance_server


def _start(governance, **kwargs):
    kwargs.setdefault("allow_nonproduction", True)
    server = create_owner_governance_server(governance, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _post_bytes(port, body=b'{"subject_id":"x"}', *, partial=False):
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    sock.settimeout(2)
    header = (
        b"POST /v1/tenants/tenant-a/members HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Authorization: Bearer test-token\r\n"
        b"Content-Type: application/json\r\n"
        + b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
        + b"Connection: close\r\n\r\n"
    )
    sock.sendall(header + (body[:1] if partial else body))
    return sock


def test_active_handler_limit_returns_retryable_503():
    entered = threading.Event()
    release = threading.Event()

    class BlockingGovernance:
        def invite_member(self, **_kwargs):
            entered.set()
            assert release.wait(4)

    server, thread = _start(
        BlockingGovernance(), max_workers=1, request_timeout=5.0
    )
    first = None
    try:
        first = _post_bytes(server.server_address[1])
        assert entered.wait(2)
        with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=2) as second:
            second.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            response = second.recv(1024)
        assert b"503 Service Unavailable" in response
        assert b"Retry-After: 1" in response
        release.set()
        first_response = first.recv(4096)
        assert b"200 OK" in first_response
    finally:
        release.set()
        if first is not None:
            first.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stalled_body_times_out_and_releases_handler_slot():
    class NoopGovernance:
        def invite_member(self, **_kwargs):
            return None

    server, thread = _start(
        NoopGovernance(), max_workers=1, request_timeout=0.5
    )
    try:
        with _post_bytes(server.server_address[1], partial=True) as slow:
            chunks = []
            while True:
                part = slow.recv(4096)
                if not part:
                    break
                chunks.append(part)
        response = b"".join(chunks)
        assert b"500 Internal Server Error" in response
        time.sleep(0.05)
        body = b'{"subject_id":"after-timeout"}'
        request = Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/tenants/tenant-a/members",
            data=body,
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as result:
            assert result.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_workers": 0},
        {"max_workers": 129},
        {"max_workers": True},
        {"request_timeout": 0},
        {"request_timeout": float("nan")},
        {"request_timeout": float("inf")},
        {"request_timeout": 10**1000},
        {"request_timeout": 120.1},
    ],
)
def test_resource_limits_reject_invalid_values(kwargs):
    with pytest.raises(ValueError):
        create_owner_governance_server(object(), **kwargs)


def test_localhost_is_verified_after_numeric_bind_resolution():
    server = create_owner_governance_server(
        object(), host="localhost", allow_nonproduction=True
    )
    try:
        assert ipaddress.ip_address(server.server_address[0]).is_loopback
    finally:
        server.server_close()
