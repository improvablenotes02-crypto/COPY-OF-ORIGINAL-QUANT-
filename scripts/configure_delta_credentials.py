"""Secure local setup for the operator's own Delta API credentials.

Prompts for secrets without echo, writes only the selected region/environment
pair to the repository-root .env file, and never enables live execution.
Run from any directory with:
    python scripts/configure_delta_credentials.py
"""
from __future__ import annotations

import getpass
import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

CREDENTIAL_NAMES = (
    "DELTA_API_KEY",
    "DELTA_API_SECRET",
    "DELTA_SANDBOX_API_KEY",
    "DELTA_SANDBOX_API_SECRET",
    "DELTA_INDIA_API_KEY",
    "DELTA_INDIA_API_SECRET",
    "DELTA_INDIA_SANDBOX_API_KEY",
    "DELTA_INDIA_SANDBOX_API_SECRET",
    # Remove obsolete names from older local examples, if present.
    "DELTA_INDIA_TESTNET_API_KEY",
    "DELTA_INDIA_TESTNET_API_SECRET",
)
MANAGED_NAMES = frozenset(("DELTA_REGION", "DELTA_ENVIRONMENT", *CREDENTIAL_NAMES))
PAIR_BY_SELECTION = {
    ("GLOBAL", "PRODUCTION"): ("DELTA_API_KEY", "DELTA_API_SECRET"),
    ("GLOBAL", "SANDBOX"): ("DELTA_SANDBOX_API_KEY", "DELTA_SANDBOX_API_SECRET"),
    ("INDIA", "PRODUCTION"): ("DELTA_INDIA_API_KEY", "DELTA_INDIA_API_SECRET"),
    ("INDIA", "SANDBOX"): ("DELTA_INDIA_SANDBOX_API_KEY", "DELTA_INDIA_SANDBOX_API_SECRET"),
}


def _secret_value(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError("%s must be text" % label)
    normalized = value.strip()
    if not normalized or any(ch in normalized for ch in ("\r", "\n", "\x00")):
        raise ValueError("%s must be non-empty and contain no line breaks" % label)
    return normalized


def configure_credentials(
    *,
    region: str,
    environment: str,
    api_key: str,
    api_secret: str,
    env_path: Path | str = ENV_PATH,
) -> Path:
    """Atomically update local .env while preserving unrelated settings."""
    selected_region = region.strip().upper() if isinstance(region, str) else ""
    selected_environment = (
        environment.strip().upper() if isinstance(environment, str) else ""
    )
    pair = PAIR_BY_SELECTION.get((selected_region, selected_environment))
    if pair is None:
        raise ValueError("select a supported Delta region and environment")
    key = _secret_value(api_key, "API key")
    secret = _secret_value(api_secret, "API secret")

    path = Path(env_path)
    if path.is_symlink():
        raise ValueError("refusing to replace a symbolic-link .env file")
    if not path.parent.is_dir():
        raise ValueError("the .env parent directory does not exist")

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
    preserved.extend((
        "# Delta credentials configured locally; do not commit this file.",
        "DELTA_REGION=%s" % selected_region,
        "DELTA_ENVIRONMENT=%s" % selected_environment,
        "%s=%s" % (pair[0], key),
        "%s=%s" % (pair[1], secret),
    ))
    content = "\n".join(preserved) + "\n"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".quantengine-env-", dir=str(path.parent)
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
            # Windows ACLs are managed by the account/host; the file remains
            # excluded from Git by .gitignore.
            pass
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return path


def _choice(prompt: str, allowed: tuple[str, ...]) -> str:
    value = input("%s (%s): " % (prompt, "/".join(allowed))).strip().upper()
    if value not in allowed:
        raise ValueError("unsupported selection")
    return value


def main() -> int:
    print("QuantEngine personal Delta credential setup")
    print("Choose the exact venue and environment for your own API key.")
    print("Secret input is hidden. Values are written only to the ignored local .env.")
    region = _choice("Region", ("INDIA", "GLOBAL"))
    environment = _choice("Environment", ("SANDBOX", "PRODUCTION"))
    confirm = input("Replace existing Delta credential entries in .env? [y/N]: ")
    if confirm.strip().lower() not in ("y", "yes"):
        print("No changes made.")
        return 0
    api_key = getpass.getpass("Delta API key (hidden): ")
    api_secret = getpass.getpass("Delta API secret (hidden): ")
    configure_credentials(
        region=region,
        environment=environment,
        api_key=api_key,
        api_secret=api_secret,
    )
    print("Local Delta credentials saved for %s/%s." % (region, environment))
    print("Secret values were not displayed. Live trading remains disarmed.")
    print("Next: python scripts/check_delta_credentials.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print("Credential setup failed: %s" % error)
        raise SystemExit(1)
