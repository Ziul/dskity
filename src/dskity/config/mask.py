"""Mask sensitive values in configuration dictionaries."""

from __future__ import annotations

import re
from typing import Any

# Keys whose values should always be masked (case-insensitive, underscore-stripped)
SENSITIVE_KEYS = frozenset({
    "password",
    "secret",
    "secretkey",
    "token",
    "apikey",
    "privatekey",
    "accesskey",
    "credentials",
})

# Patterns in values that indicate embedded credentials
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"://[^/]*:[^@]+@"),  # URLs with user:pass@host
    re.compile(r"^(hvs\.|s\.)"),      # Vault tokens
    re.compile(r"^sk[-_]"),           # API keys (Stripe, OpenAI, etc.)
)

MASK = "***"


def mask_secrets(data: Any) -> Any:
    """Recursively mask sensitive values in a dict/list structure.

    Rules:
    - If a dict key matches SENSITIVE_KEYS (case-insensitive), mask the value.
    - If a string value matches SENSITIVE_VALUE_PATTERNS, mask it.
    - Recurse into nested dicts and lists.
    """
    if isinstance(data, dict):
        return {k: _mask_value(k, v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_secrets(item) for item in data]
    return data


def _mask_value(key: str, value: Any) -> Any:
    """Decide whether to mask a value based on its key and content."""
    key_lower = key.lower().replace("_", "").replace("-", "")

    if key_lower in SENSITIVE_KEYS:
        if isinstance(value, str) and value:
            return MASK
        return value

    if isinstance(value, str) and value:
        for pattern in SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                return MASK

    if isinstance(value, dict):
        return mask_secrets(value)

    if isinstance(value, list):
        return [mask_secrets(item) for item in value]

    return value
