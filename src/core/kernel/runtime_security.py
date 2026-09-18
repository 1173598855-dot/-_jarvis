"""Secure runtime defaults shared by the Python HTTP services."""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def configured_allowed_origins(
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Return an exact origin allowlist; wildcard values are never accepted."""
    raw = _environment(environ).get("JARVIS_ALLOWED_ORIGINS", "")
    origins = [
        origin.strip()
        for origin in raw.split(",")
        if origin.strip() and origin.strip() != "*"
    ]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def terminal_access_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Terminal HTTP access needs both an explicit flag and a secret token."""
    values = _environment(environ)
    return (
        values.get("JARVIS_TERMINAL_ENABLED", "").casefold() == "true"
        and bool(values.get("JARVIS_TERMINAL_TOKEN", ""))
    )


def terminal_request_is_authorized(
    provided_token: str | None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Compare the capability token without exposing a prefix timing oracle."""
    values = _environment(environ)
    expected_token = values.get("JARVIS_TERMINAL_TOKEN", "")
    return bool(
        terminal_access_enabled(values)
        and isinstance(provided_token, str)
        and hmac.compare_digest(provided_token, expected_token)
    )
