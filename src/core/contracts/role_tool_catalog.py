"""Static built-in role-tool catalog and trusted assembly evidence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .role_tool_protocol import (
    RoleToolDefinition,
    RoleToolProtocolError,
    stable_json_bytes,
)

ROLE_TOOL_ASSEMBLY_SCHEMA_VERSION = 1
ROLE_TOOL_SOURCE_PATH = "src/core/brain/read_only_role_tools.py"
MAX_MEMORY_RESULTS = 20
_CAPABILITY_ID_RE = re.compile(
    r"^role_tool:[a-z0-9][a-z0-9._-]{0,127}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _object_schema(
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }


@dataclass(frozen=True, slots=True)
class RoleToolCatalogEntry:
    """One source-controlled role tool without an executable handler."""

    capability_id: str
    definition: RoleToolDefinition
    permissions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not _CAPABILITY_ID_RE.fullmatch(
            self.capability_id
        ):
            raise RoleToolProtocolError("Role tool capability ID is invalid")
        if not isinstance(self.definition, RoleToolDefinition):
            raise RoleToolProtocolError(
                "Role tool catalog entry requires a definition"
            )
        if not isinstance(self.permissions, tuple) or any(
            not isinstance(permission, str) or not permission
            for permission in self.permissions
        ):
            raise RoleToolProtocolError(
                "Role tool permissions must be non-empty strings"
            )
        normalized = tuple(sorted(set(self.permissions)))
        object.__setattr__(self, "permissions", normalized)

    def descriptor(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "definition": self.definition.to_ollama()["function"],
            "permissions": list(self.permissions),
        }

    @property
    def descriptor_sha256(self) -> str:
        return hashlib.sha256(stable_json_bytes(self.descriptor())).hexdigest()


ROLE_TOOL_CATALOG = tuple(sorted((
    RoleToolCatalogEntry(
        capability_id="role_tool:system_status",
        definition=RoleToolDefinition(
            "system_status",
            "Read bounded host and repository-volume status",
            _object_schema(),
        ),
        permissions=("system.read",),
    ),
    RoleToolCatalogEntry(
        capability_id="role_tool:model_list",
        definition=RoleToolDefinition(
            "model_list",
            "List models from the trusted Ollama service",
            _object_schema({
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                },
            }),
        ),
        permissions=("ollama.models.read",),
    ),
    RoleToolCatalogEntry(
        capability_id="role_tool:orchestrator_status",
        definition=RoleToolDefinition(
            "orchestrator_status",
            "Read the trusted role registry and Worker isolation status",
            _object_schema(),
        ),
        permissions=("roles.read",),
    ),
    RoleToolCatalogEntry(
        capability_id="role_tool:memory_search",
        definition=RoleToolDefinition(
            "memory_search",
            "Search bounded entries in the trusted memory store",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 256},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_MEMORY_RESULTS,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        permissions=("memory.read",),
    ),
    RoleToolCatalogEntry(
        capability_id="role_tool:repository_metadata",
        definition=RoleToolDefinition(
            "repository_metadata",
            "Read bounded Git metadata from the trusted repository",
            _object_schema(),
        ),
        permissions=("repository.read",),
    ),
), key=lambda entry: entry.capability_id))

ROLE_TOOL_CAPABILITY_IDS = tuple(
    entry.capability_id for entry in ROLE_TOOL_CATALOG
)

if len(ROLE_TOOL_CAPABILITY_IDS) != len(set(ROLE_TOOL_CAPABILITY_IDS)):
    raise RoleToolProtocolError("Role tool capability IDs must be unique")
if len({entry.definition.name for entry in ROLE_TOOL_CATALOG}) != len(
    ROLE_TOOL_CATALOG
):
    raise RoleToolProtocolError("Role tool definition names must be unique")


def role_tool_catalog_digest() -> str:
    """Return a deterministic digest over all non-executable descriptors."""
    descriptors = [entry.descriptor() for entry in ROLE_TOOL_CATALOG]
    return hashlib.sha256(stable_json_bytes(descriptors)).hexdigest()


def role_tool_definitions() -> dict[str, RoleToolDefinition]:
    """Return a new name-indexed mapping of the fixed definitions."""
    return {
        entry.definition.name: entry.definition
        for entry in ROLE_TOOL_CATALOG
    }


@dataclass(frozen=True, slots=True)
class RoleToolAssembly:
    """Strict JSON-safe evidence that the complete static catalog was selected."""

    schema_version: int
    capability_ids: tuple[str, ...]
    catalog_sha256: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or (
            self.schema_version != ROLE_TOOL_ASSEMBLY_SCHEMA_VERSION
        ):
            raise RoleToolProtocolError(
                "Role tool assembly schema version is invalid"
            )
        if type(self.capability_ids) is not tuple or any(
            type(capability_id) is not str
            for capability_id in self.capability_ids
        ):
            raise RoleToolProtocolError(
                "Role tool assembly capability IDs must be an array of strings"
            )
        if self.capability_ids != ROLE_TOOL_CAPABILITY_IDS:
            raise RoleToolProtocolError(
                "Role tool assembly capability IDs do not match the catalog"
            )
        if type(self.catalog_sha256) is not str or not _SHA256_RE.fullmatch(
            self.catalog_sha256
        ):
            raise RoleToolProtocolError(
                "Role tool assembly catalog digest is invalid"
            )
        if self.catalog_sha256 != role_tool_catalog_digest():
            raise RoleToolProtocolError(
                "Role tool assembly catalog digest does not match"
            )

    @classmethod
    def for_catalog(cls) -> "RoleToolAssembly":
        return cls(
            schema_version=ROLE_TOOL_ASSEMBLY_SCHEMA_VERSION,
            capability_ids=ROLE_TOOL_CAPABILITY_IDS,
            catalog_sha256=role_tool_catalog_digest(),
        )

    @classmethod
    def from_value(cls, value: object) -> "RoleToolAssembly":
        if type(value) is not dict:
            raise RoleToolProtocolError(
                "Role tool assembly must be an object"
            )
        expected_fields = {
            "schema_version",
            "capability_ids",
            "catalog_sha256",
        }
        if (
            len(value) != len(expected_fields)
            or any(type(field) is not str for field in value)
            or set(value) != expected_fields
        ):
            raise RoleToolProtocolError(
                "Role tool assembly fields are invalid"
            )
        capability_ids = value["capability_ids"]
        if type(capability_ids) is not list:
            raise RoleToolProtocolError(
                "Role tool assembly capability IDs must be an array"
            )
        return cls(
            schema_version=value["schema_version"],
            capability_ids=tuple(capability_ids),
            catalog_sha256=value["catalog_sha256"],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capability_ids": list(self.capability_ids),
            "catalog_sha256": self.catalog_sha256,
        }


__all__ = [
    "MAX_MEMORY_RESULTS",
    "ROLE_TOOL_ASSEMBLY_SCHEMA_VERSION",
    "ROLE_TOOL_CAPABILITY_IDS",
    "ROLE_TOOL_CATALOG",
    "ROLE_TOOL_SOURCE_PATH",
    "RoleToolAssembly",
    "RoleToolCatalogEntry",
    "role_tool_catalog_digest",
    "role_tool_definitions",
]
