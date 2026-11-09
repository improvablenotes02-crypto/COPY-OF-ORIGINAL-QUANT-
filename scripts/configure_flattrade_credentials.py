"""Secure local Flattrade login, token exchange and .env provisioning.

The callback listener binds only to loopback. The API secret, request code,
hash and returned session token are never printed. No order endpoints are
called. The registered Flattrade redirect URI must match the selected port.
"""
from __future__ import annotations

import getpass
import os
import sys
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from core.exchanges.flattrade.flattrade_auth import (
    TOKEN_EXCHANGE_URL,
    build_token_exchange_payload,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
AUTH_URL = "https://auth.flattrade.in/"
MANAGED_NAMES = frozenset({
    "FLATTRADE_API_KEY",
    "FLATTRADE_API_SECRET",
    "FLATTRADE_USER_ID",
    "FLATTRADE_SESSION_TOKEN",
})


class FlattradeSetupError(RuntimeError):
    """Safe operator-facing setup failure; contains no provider payload."""


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise FlattradeSetupError("%s is missing or invalid" % label)
    normalized = value.strip()
    if not normalized or any(ch in normalized for ch in ("\r", "\n", "\x00")):
        raise FlattradeSetupError("%s is missing or invalid" % label)
    return normalized


def parse_callback_target(target: str) -> str:
    """Extract exactly one short-lived Flattrade request code from callback URL."""
    if not isinstance(target, str):
        raise FlattradeSetupError("callback URL is invalid")
    parsed = urlsplit(target)
    if parsed.path not in ("", "/"):
        raise FlattradeSetupError("callback path is not registered")
    values = parse_qs(parsed.query, keep_blank_values=True).get("code", [])
    if len(values) != 1:
        raise FlattradeSetupError("callback must contain exactly one request code")
    return _required_text(values[0], "request code")


def exchange_request_code(*, api_key: str, api_secret: str, request_code: str, post_json=None):
    """Exchange one-time request code for (client/user id, session token)."""
    payload = build_token_exchange_payload(
        api_key=api_key, request_code=request_code, api_secret=api_secret
    )
    if post_json is None:
        import httpx

        post_json = httpx.post
    try:
        response = post_json(
            TOKEN_EXCHANGE_URL, json=payload, timeout=15.0
        )
        response.raise_for_status()
        body = response.json()
    except Exception as error:
        raise FlattradeSetupError("Flattrade token exchange request failed") from error

    if not isinstance(body, dict) or body.get("status") != "Ok":
        raise FlattradeSetupError("Flattrade rejected the token exchange")
    user_id = _required_text(body.get("client"), "Flattrade client id")
    session_token = _required_text(body.get("token"), "Flattrade session token")
    return user_id, session_token


def store_credentials(
    *, api_key: str, api_secret: str, user_id: str, session_token: str,
    env_path: Path | str = ENV_PATH,
) -> Path:
    """Atomically persist only the managed Flattrade values in ignored .env."""
    values = {
        "FLATTRADE_API_KEY": _required_text(api_key, "API key"),
        "FLATTRADE_API_SECRET": _required_text(api_secret, "API secret"),
        "FLATTRADE_USER_ID": _required_text(user_id, "client id"),
        "FLATTRADE_SESSION_TOKEN": _required_text(session_token, "session token"),
    }
    path = Path(env_path)
    if path.is_symlink():
        raise FlattradeSetupError("refusing to replace a symbolic-link .env file")
    if not path.parent.is_dir():
        raise FlattradeSetupError(".env parent directory does not exist")

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    preserved = []
    for line in existing.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            preserved.append(line)
            continue
        name = candidate.split("=", 1)[0].strip()
        if name not in MANAGED_NAMES:
            preserved.append(line)
    while preserved and not preserved[-1].strip():
        preserved.pop()
    if preserved:
        preserved.append("")
    preserved.append("# Flattrade credentials configured locally; never commit this file.")
    preserved.extend("%s=%s" % item for item in values.items())
    content = "\n".join(preserved) + "\n"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".quantengine-flattrade-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            # Windows ACLs are managed by the local account/host.
            pass
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return path


class _CallbackHTTPServer(HTTPServer):
    request_code = None
    timeout = 180


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            code = parse_callback_target(self.path)
        except FlattradeSetupError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"QuantEngine could not validate the Flattrade callback. Return to the terminal.")
            return
        self.server.request_code = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(
            b"<!doctype html><title>QuantEngine</title>"
            b"<p>Flattrade authorization received. You may close this tab and return to QuantEngine.</p>"
        )

    def log_message(self, format, *args):
        # Never log callback URLs: they contain a one-time request code.
        return


def capture_request_code(*, port: int = 8080, timeout: float = 180.0, on_listening=None) -> str:
    """Receive one callback on loopback only; never print/log the request code."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise FlattradeSetupError("callback port is invalid")
    server = _CallbackHTTPServer(("127.0.0.1", port), _CallbackHandler)
    deadline = time.monotonic() + timeout
    try:
        if callable(on_listening):
            on_listening()
        while not server.request_code:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FlattradeSetupError("Flattrade callback timed out or was not received")
            server.timeout = remaining
            server.handle_request()
        return server.request_code
    finally:
        server.server_close()


def configure_credentials(
    *, api_key: str, api_secret: str, request_code: str,
    env_path: Path | str = ENV_PATH, post_json=None,
) -> Path:
    key = _required_text(api_key, "API key")
    secret = _required_text(api_secret, "API secret")
    code = _required_text(request_code, "request code")
    user_id, token = exchange_request_code(
        api_key=key, api_secret=secret, request_code=code, post_json=post_json
    )
    return store_credentials(
        api_key=key, api_secret=secret, user_id=user_id,
        session_token=token, env_path=env_path,
    )


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Refusing Flattrade credential input without an interactive terminal.")
        return 2
    print("QuantEngine personal Flattrade setup (read-only authentication only)")
    print("Register this exact redirect URL in your Flattrade API application.")
    raw_port = input("Redirect port [8080]: ").strip() or "8080"
    try:
        port = int(raw_port)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("Invalid callback port.")
        return 2
    redirect_uri = "http://127.0.0.1:%d/" % port
    print("Required registered redirect URL: " + redirect_uri)
    confirm = input("Replace existing Flattrade credential entries in .env after successful login? [y/N]: ")
    if confirm.strip().lower() not in ("y", "yes"):
        print("No changes made.")
        return 0
    api_key = getpass.getpass("Flattrade API key (hidden): ")
    api_secret = getpass.getpass("Flattrade API secret (hidden): ")
    try:
        key = _required_text(api_key, "API key")
        secret = _required_text(api_secret, "API secret")
        login_url = AUTH_URL + "?" + urlencode({"app_key": key})
        def _open_login_page():
            print("Waiting for local Flattrade authorization callback...")
            print("If your browser does not open, use this login URL:")
            print(login_url)
            webbrowser.open(login_url)

        # Bind the loopback listener BEFORE opening the browser, so a fast
        # redirect cannot race ahead of the local callback server.
        request_code = capture_request_code(
            port=port, on_listening=_open_login_page
        )
        configure_credentials(
            api_key=key, api_secret=secret, request_code=request_code
        )
    except (OSError, FlattradeSetupError):
        print("Flattrade setup failed. Check the registered redirect URL, API credentials and network; no secret or provider response was printed.")
        return 1
    print("Flattrade credentials saved locally in the ignored .env file.")
    print("Session token is stored but not displayed. It expires daily at 5:00 AM IST.")
    print("No balances, positions or orders were accessed; live execution remains disarmed.")
    print("Next integration step: Flattrade read-only market-data adapter (not yet enabled).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
