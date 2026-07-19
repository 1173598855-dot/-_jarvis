from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


REDACTED = "[REDACTED]"
_SECRET_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "token",
    "private_key",
    "cookie",
)
_BEARER_PATTERN = re.compile(r"(?i)(\bbearer\s+)([^\s,;]+)")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:authorization|api[\s_-]?key|password|passwd|secret|token|"
    r"private[\s_-]?key|cookie)\b\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;]+)"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_key(key: object) -> str:
    if not isinstance(key, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _is_secret_key(key: object) -> bool:
    normalized = _normalize_key(key)
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def redact_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    redacted = _PRIVATE_KEY_BLOCK.sub(REDACTED, text)
    redacted = _BEARER_PATTERN.sub(lambda match: match.group(1) + REDACTED, redacted)
    return _ASSIGNMENT_PATTERN.sub(
        lambda match: match.group(1) + REDACTED,
        redacted,
    )


def redact_value(value: object, key: str | None = None) -> object:
    if key is not None and _is_secret_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            item_key: redact_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, set):
        return {redact_value(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
