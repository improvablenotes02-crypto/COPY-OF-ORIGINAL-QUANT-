"""Phase 474: personal Delta credential selection and repository safety."""
from pathlib import Path
import pytest

from scripts.configure_delta_credentials import CREDENTIAL_NAMES, configure_credentials


@pytest.mark.parametrize(
    "region,environment,key_name,secret_name",
    [
        ("GLOBAL", "PRODUCTION", "DELTA_API_KEY", "DELTA_API_SECRET"),
        ("GLOBAL", "SANDBOX", "DELTA_SANDBOX_API_KEY", "DELTA_SANDBOX_API_SECRET"),
        ("INDIA", "PRODUCTION", "DELTA_INDIA_API_KEY", "DELTA_INDIA_API_SECRET"),
        ("INDIA", "SANDBOX", "DELTA_INDIA_SANDBOX_API_KEY", "DELTA_INDIA_SANDBOX_API_SECRET"),
    ],
)
def test_each_region_environment_uses_only_its_exact_credential_pair(
    tmp_path, region, environment, key_name, secret_name
):
    env = tmp_path / ".env"
    env.write_text(
        "PAPER_MODE=True\nALLOW_LIVE=False\nLIVE_EXECUTE=False\n"
        "DELTA_API_KEY=stale-key\nDELTA_API_SECRET=stale-secret\n",
        encoding="utf-8",
    )
    configure_credentials(
        region=region, environment=environment,
        api_key="synthetic-key", api_secret="synthetic-secret",
        env_path=env,
    )
    rendered = env.read_text(encoding="utf-8")
    assert f"DELTA_REGION={region}" in rendered
    assert f"DELTA_ENVIRONMENT={environment}" in rendered
    assert f"{key_name}=synthetic-key" in rendered
    assert f"{secret_name}=synthetic-secret" in rendered
    assert "PAPER_MODE=True" in rendered
    assert "ALLOW_LIVE=False" in rendered
    assert "LIVE_EXECUTE=False" in rendered
    for name in CREDENTIAL_NAMES:
        if name not in (key_name, secret_name):
            assert f"{name}=" not in rendered


def test_repository_ignores_local_env_but_keeps_example_template():
    root = Path(__file__).resolve().parents[1]
    lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines
    assert ".env.*" in lines
    assert "!.env.example" in lines
