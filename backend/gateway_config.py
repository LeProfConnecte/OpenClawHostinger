"""
Gateway configuration utilities for writing dynamic environment variables.

This module handles writing secrets (tokens, API keys) to an environment file
that gets loaded by the supervised gateway wrapper script.
"""

import os
import re
import stat
from pathlib import Path

__all__ = ["write_gateway_env", "clear_gateway_env", "sanitize_shell_value"]

# Path to the gateway environment file
# Use CLAWDBOT_HOME env var if set, otherwise fall back to ~/.clawdbot
GATEWAY_ENV_DIR = os.environ.get("CLAWDBOT_HOME") or os.path.expanduser("~/.clawdbot")
GATEWAY_ENV_FILE = os.path.join(GATEWAY_ENV_DIR, "gateway.env")

# Strict pattern for values that are safe to put in shell export statements
# Only allow alphanumeric, dashes, underscores, dots, colons, slashes, and plus signs
_SAFE_SHELL_VALUE_RE = re.compile(r'^[a-zA-Z0-9\-_.:+/=]+$')


def sanitize_shell_value(value: str) -> str:
    """
    Validate and sanitize a value for use in a shell export statement.

    Raises ValueError if the value contains dangerous characters that could
    enable shell injection (quotes, backticks, $, semicolons, etc.).
    """
    if not value:
        raise ValueError("Empty value not allowed in shell export")
    if not _SAFE_SHELL_VALUE_RE.match(value):
        raise ValueError(
            f"Value contains unsafe characters for shell export. "
            f"Only alphanumeric, dashes, underscores, dots, colons, slashes, plus, and equals are allowed."
        )
    return value


def write_gateway_env(token: str, api_key: str = None, provider: str = "emergent") -> None:
    """
    Write secrets to env file before starting gateway.

    This allows the supervisor-managed gateway to load dynamic
    configuration that changes each time the gateway starts.

    Args:
        token: The gateway authentication token
        api_key: Optional API key for the provider
        provider: The provider name ("emergent", "anthropic", "openai", or "openrouter")

    Raises:
        ValueError: If token or api_key contain unsafe shell characters
    """
    # Ensure directory exists
    os.makedirs(GATEWAY_ENV_DIR, exist_ok=True)

    # Sanitize all values before writing to shell export statements
    safe_token = sanitize_shell_value(token)

    # Build environment file content
    lines = [
        f'export CLAWDBOT_GATEWAY_TOKEN="{safe_token}"',
    ]

    # Add provider-specific API keys
    if api_key:
        safe_key = sanitize_shell_value(api_key)
        if provider == "anthropic":
            lines.append(f'export ANTHROPIC_API_KEY="{safe_key}"')
        elif provider == "openai":
            lines.append(f'export OPENAI_API_KEY="{safe_key}"')
        elif provider == "openrouter":
            lines.append(f'export OPENROUTER_API_KEY="{safe_key}"')
        # For emergent provider, the API key is in the config file, not env var

    # Write the file
    content = "\n".join(lines) + "\n"

    with open(GATEWAY_ENV_FILE, 'w') as f:
        f.write(content)

    # Set secure permissions (readable only by owner)
    os.chmod(GATEWAY_ENV_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0o600


def clear_gateway_env() -> None:
    """
    Clear the gateway environment file.

    Called when stopping the gateway to remove sensitive credentials.
    """
    if os.path.exists(GATEWAY_ENV_FILE):
        os.remove(GATEWAY_ENV_FILE)
