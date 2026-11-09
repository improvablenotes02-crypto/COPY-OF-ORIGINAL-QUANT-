"""Tests for secure local Delta credential setup; no real keys or network."""
import os
import stat

import pytest

from scripts.configure_delta_credentials import configure_credentials


def test_setup_writes_only_selected_pair_and_preserves_other_settings(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "SYMBOLS=NIFTY\n"
        "DELTA_API_KEY=old-global-key\n"
        "DELTA_INDIA_TESTNET_API_SECRET=old-name\n"
        "PAPER_MODE=True\n",
        encoding="utf-8",
    )

    configure_credentials(
        region="india",
        environment="sandbox",
        api_key="synthetic-new-key",
        api_secret="synthetic-new-secret",
        env_path=env,
    )

    rendered = env.read_text(encoding="utf-8")
    assert "SYMBOLS=NIFTY" in rendered
    assert "PAPER_MODE=True" in rendered
    assert "DELTA_REGION=INDIA" in rendered
    assert "DELTA_ENVIRONMENT=SANDBOX" in rendered
    assert "DELTA_INDIA_SANDBOX_API_KEY=synthetic-new-key" in rendered
    assert "DELTA_INDIA_SANDBOX_API_SECRET=synthetic-new-secret" in rendered
    assert "DELTA_API_KEY=" not in rendered
    assert "DELTA_INDIA_TESTNET_API_SECRET" not in rendered
    assert rendered.count("DELTA_REGION=") == 1


def test_setup_rejects_invalid_selection_or_secret_without_mutating_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PAPER_MODE=True\n", encoding="utf-8")
    before = env.read_bytes()

    with pytest.raises(ValueError):
        configure_credentials(
            region="UNKNOWN", environment="SANDBOX",
            api_key="key", api_secret="secret", env_path=env,
        )
    with pytest.raises(ValueError):
        configure_credentials(
            region="INDIA", environment="SANDBOX",
            api_key="key\nDELTA_API_SECRET=inject",
            api_secret="secret", env_path=env,
        )
    with pytest.raises(ValueError):
        configure_credentials(
            region="INDIA", environment="SANDBOX",
            api_key="key", api_secret="   ", env_path=env,
        )
    assert env.read_bytes() == before


def test_setup_refuses_symlink_env_file(tmp_path):
    target = tmp_path / "target.env"
    target.write_text("PAPER_MODE=True\n", encoding="utf-8")
    env = tmp_path / ".env"
    try:
        env.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(ValueError, match="symbolic-link"):
        configure_credentials(
            region="GLOBAL", environment="SANDBOX",
            api_key="key", api_secret="secret", env_path=env,
        )
    assert target.read_text(encoding="utf-8") == "PAPER_MODE=True\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not Windows ACLs")
def test_setup_restricts_local_env_permissions(tmp_path):
    env = tmp_path / ".env"
    configure_credentials(
        region="GLOBAL", environment="SANDBOX",
        api_key="key", api_secret="secret", env_path=env,
    )
    assert stat.S_IMODE(env.stat().st_mode) == 0o600

def test_setup_refuses_noninteractive_secret_input(monkeypatch):
    import io
    import sys

    from scripts import configure_delta_credentials as setup

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", captured)
    assert setup.main() == 2
    assert "interactive terminal" in captured.getvalue()

