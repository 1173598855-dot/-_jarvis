"""Shared request validation and response shaping for capability APIs."""

from __future__ import annotations

import re
from typing import Iterable

from .capability_manifest import (
    SCHEMA_VERSION,
    CapabilityKind,
    CapabilityRisk,
    CapabilityValidationError,
)
from .capability_registry import CapabilityRegistry
from .capability_resolver import (
    CapabilityQuery,
    CapabilityResolver,
    CompatibilityTarget,
)


_QUERY_PARAMETERS = {"q", "kind", "compatible_only", "max_risk", "limit"}
_INTEGER_RE = re.compile(r"^[0-9]+$")
CAPABILITY_SNAPSHOT_CACHE_TTL_SECONDS = 2.0
MAX_PUBLIC_CAPABILITY_ISSUES = 100


class CapabilityRegistryRequestError(ValueError):
    """A public invalid-query failure with no internal implementation detail."""


def parse_capability_query_items(
    items: Iterable[tuple[str, str]],
) -> CapabilityQuery:
    """Build one strict scalar query from decoded query-string items."""
    values: dict[str, str] = {}
    for name, value in items:
        if name not in _QUERY_PARAMETERS:
            raise CapabilityRegistryRequestError("Unknown query parameter")
        if name in values:
            raise CapabilityRegistryRequestError(
                f"Query parameter {name} must be provided once"
            )
        if not isinstance(value, str):
            raise CapabilityRegistryRequestError(
                f"Query parameter {name} must be a string"
            )
        values[name] = value

    try:
        kind = (
            CapabilityKind(values["kind"])
            if "kind" in values
            else None
        )
        max_risk = CapabilityRisk(values.get("max_risk", "high"))

        compatible_text = values.get("compatible_only", "false")
        if compatible_text not in {"true", "false"}:
            raise CapabilityRegistryRequestError(
                "compatible_only must be true or false"
            )
        compatible_only = compatible_text == "true"

        limit_text = values.get("limit", "20")
        if not _INTEGER_RE.fullmatch(limit_text):
            raise CapabilityRegistryRequestError("limit must be an integer")
        limit = int(limit_text)

        return CapabilityQuery(
            query=values.get("q", ""),
            kind=kind,
            compatible_only=compatible_only,
            max_risk=max_risk,
            limit=limit,
        )
    except CapabilityRegistryRequestError:
        raise
    except (CapabilityValidationError, ValueError) as error:
        raise CapabilityRegistryRequestError("Capability query is invalid") from error


def resolve_capability_registry(
    registry: CapabilityRegistry,
    resolver: CapabilityResolver,
    target: CompatibilityTarget,
    query: CapabilityQuery,
) -> dict[str, object]:
    """Resolve a local snapshot into its explicitly public wire representation."""
    snapshot = registry.snapshot()
    matches = resolver.resolve(snapshot, query, target)
    issues = list(snapshot.issues[:MAX_PUBLIC_CAPABILITY_ISSUES])
    if len(snapshot.issues) > MAX_PUBLIC_CAPABILITY_ISSUES:
        issues[-1] = "issues_truncated"
    return {
        "schema_version": SCHEMA_VERSION,
        "capabilities": [
            match.to_public_dict(include_match=False)
            for match in matches
        ],
        "count": len(matches),
        "issues": issues,
    }
