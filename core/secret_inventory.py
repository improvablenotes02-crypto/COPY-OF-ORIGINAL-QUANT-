"""Canonical names for QuantEngine credentials and bearer secrets.

Keep this inventory free of secret values. Scanner and API redaction import it.
"""
DELTA_CREDENTIAL_ENV_VARS = (
    "DELTA_API_KEY",
    "DELTA_API_SECRET",
    "DELTA_SANDBOX_API_KEY",
    "DELTA_SANDBOX_API_SECRET",
    "DELTA_INDIA_API_KEY",
    "DELTA_INDIA_API_SECRET",
    "DELTA_INDIA_SANDBOX_API_KEY",
    "DELTA_INDIA_SANDBOX_API_SECRET",
    # Retained only to detect obsolete credentials in old local files/history.
    "DELTA_INDIA_TESTNET_API_KEY",
    "DELTA_INDIA_TESTNET_API_SECRET",
)
OTHER_SECRET_ENV_VARS = (
    "CONTROL_API_TOKEN",
    "REMOTE_VIEW_TOKEN",
    "REMOTE_CONTROL_TOKEN",
    "REMOTE_EMERGENCY_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
)
ALL_SECRET_ENV_VARS = DELTA_CREDENTIAL_ENV_VARS + OTHER_SECRET_ENV_VARS
