"""Bounded JSON file input for local command-line entry points."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_CLI_JSON_BYTES = 8 * 1024 * 1024


def read_bounded_json(
    path: str | Path,
    *,
    label: str = "JSON input",
    max_bytes: int = MAX_CLI_JSON_BYTES,
) -> Any:
    """Read and decode one UTF-8 JSON file without an unbounded read."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")

    candidate = Path(path)
    if candidate.stat().st_size > max_bytes:
        raise ValueError(f"{label} exceeds {max_bytes} bytes")

    with candidate.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"{label} exceeds {max_bytes} bytes")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} must be valid UTF-8") from error
    return json.loads(text)


__all__ = ["MAX_CLI_JSON_BYTES", "read_bounded_json"]
