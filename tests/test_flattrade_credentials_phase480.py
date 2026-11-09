"""Phase 480: secure local Flattrade token provisioning tests."""
import hashlib
from pathlib import Path

import pytest

from scripts.configure_flattrade_credentials import (
    FlattradeSetupError,
    configure_credentials,
    parse_callback_target,
    store_credentials,
)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def test_callback_parser_accepts_one_code_and_rejects_ambiguous_or_wrong_path():
    assert parse_callback_target("/?code=one-time-code") == "one-time-code"
    for target in ("/?code=", "/?code=a&code=b", "/unexpected?code=x", "/?state=x"):
        with pytest.raises(FlattradeSetupError):
            parse_callback_target(target)


def test_configure_exchanges_one_time_code_and_stores_only_expected_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PAPER_MODE=True\nALLOW_LIVE=False\n", encoding="utf-8")
    calls = []

    def post_json(url, *, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse({
            "status": "Ok", "client": "FTUSER123",
            "token": "synthetic-session-token",
        })

    configure_credentials(
        api_key="synthetic-app-key",
        api_secret="synthetic-app-secret",
        request_code="synthetic-request-code",
        env_path=env,
        post_json=post_json,
    )
    rendered = env.read_text(encoding="utf-8")
    assert len(calls) == 1
    assert calls[0][0] == "https://authapi.flattrade.in/trade/apitoken"
    assert calls[0][2] == 15.0
    assert calls[0][1]["api_secret"] == hashlib.sha256(
        b"synthetic-app-keysynthetic-request-codesynthetic-app-secret"
    ).hexdigest()
    assert "FLATTRADE_USER_ID=FTUSER123" in rendered
    assert "FLATTRADE_SESSION_TOKEN=synthetic-session-token" in rendered
    assert "PAPER_MODE=True" in rendered
    assert "ALLOW_LIVE=False" in rendered
    assert "synthetic-app-secret" in rendered
    assert "synthetic-session-token" in rendered


def test_failed_exchange_never_mutates_existing_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PAPER_MODE=True\n", encoding="utf-8")
    before = env.read_bytes()

    def rejected(url, *, json, timeout):
        return FakeResponse({"status": "Not_Ok", "emsg": "sensitive provider text"})

    with pytest.raises(FlattradeSetupError):
        configure_credentials(
            api_key="key", api_secret="secret", request_code="code",
            env_path=env, post_json=rejected,
        )
    assert env.read_bytes() == before


def test_store_credentials_replaces_only_flattrade_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "PAPER_MODE=True\nFLATTRADE_API_KEY=old\n"
        "FLATTRADE_SESSION_TOKEN=expired\nDELTA_API_KEY=delta-key\n",
        encoding="utf-8",
    )
    store_credentials(
        api_key="new-key", api_secret="new-secret", user_id="user-1",
        session_token="new-token", env_path=env,
    )
    rendered = env.read_text(encoding="utf-8")
    assert "PAPER_MODE=True" in rendered
    assert "DELTA_API_KEY=delta-key" in rendered
    assert "FLATTRADE_API_KEY=new-key" in rendered
    assert "FLATTRADE_API_SECRET=new-secret" in rendered
    assert "FLATTRADE_USER_ID=user-1" in rendered
    assert "FLATTRADE_SESSION_TOKEN=new-token" in rendered
    assert rendered.count("FLATTRADE_API_KEY=") == 1


def test_store_credentials_refuses_symlink_env_file(tmp_path):
    target = tmp_path / "target.env"
    target.write_text("PAPER_MODE=True\n", encoding="utf-8")
    env = tmp_path / ".env"
    try:
        env.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(FlattradeSetupError, match="symbolic-link"):
        store_credentials(
            api_key="key", api_secret="secret", user_id="uid",
            session_token="token", env_path=env,
        )
    assert target.read_text(encoding="utf-8") == "PAPER_MODE=True\n"
