from __future__ import annotations

import re
from collections.abc import Mapping

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
_STANDALONE_CREDENTIAL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{20,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|eyJ[A-Za-z0-9_-]{7,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r")(?![A-Za-z0-9_-])"
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
    redacted = _ASSIGNMENT_PATTERN.sub(
        lambda match: match.group(1) + REDACTED,
        redacted,
    )
    return _STANDALONE_CREDENTIAL_PATTERN.sub(REDACTED, redacted)


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
