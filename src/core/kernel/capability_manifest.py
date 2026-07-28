"""Versioned public records for locally available capabilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable, Mapping, Optional


SCHEMA_VERSION = 1
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMPATIBILITY_STATUSES = {"unknown", "compatible", "incompatible"}
_PROVENANCE_STATUSES = {"incomplete", "complete", "verified"}


class CapabilityValidationError(ValueError):
    """A stable validation failure that is safe to expose as a code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CapabilityKind(str, Enum):
    SKILL = "skill"
    PLUGIN = "plugin"
    UI_COMPONENT = "ui_component"


class CapabilityLifecycle(str, Enum):
    DISCOVERED = "discovered"
    DISABLED = "disabled"
    ENABLED = "enabled"
    INVALID = "invalid"


class CapabilityHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INVALID = "invalid"


class CapabilityRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _validate_text(value: str, field_name: str, *, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CapabilityValidationError("field_type_invalid", f"{field_name} must be a string")
    if not empty and not value:
        raise CapabilityValidationError("field_empty", f"{field_name} must not be empty")
    if len(value) > maximum:
        raise CapabilityValidationError("field_too_long", f"{field_name} is too long")
    if any(ord(character) < 32 for character in value):
        raise CapabilityValidationError("field_control_character", f"{field_name} has control characters")
    return value


def _validate_relative_path(value: str, field_name: str) -> str:
    _validate_text(value, field_name, maximum=1024)
    if "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise CapabilityValidationError("path_invalid", f"{field_name} must be a POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        raise CapabilityValidationError("path_invalid", f"{field_name} must stay relative")
    return path.as_posix()


def _normalize_codes(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized = []
    for value in values:
        _validate_text(value, field_name, maximum=128)
        normalized.append(value)
    return tuple(sorted(set(normalized)))


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    kind: CapabilityKind
    name: str
    version: Optional[str]
    description: str
    relative_path: str
    entrypoint: Optional[str]
    lifecycle: CapabilityLifecycle
    permissions: tuple[str, ...]
    compatibility: tuple[tuple[str, str], ...]
    compatibility_status: str
    source_url: Optional[str]
    license_name: Optional[str]
    sha256: Optional[str]
    provenance_status: str
    health: CapabilityHealth
    health_issues: tuple[str, ...]
    risk: CapabilityRisk
    risk_reasons: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        capability_id: str,
        kind: CapabilityKind,
        name: str,
        version: Optional[str],
        description: str,
        relative_path: str,
        entrypoint: Optional[str],
        lifecycle: CapabilityLifecycle = CapabilityLifecycle.DISCOVERED,
        permissions: Iterable[str] = (),
        compatibility: Optional[Mapping[str, str]] = None,
        compatibility_status: str = "unknown",
        source_url: Optional[str] = None,
        license_name: Optional[str] = None,
        sha256: Optional[str] = None,
        provenance_status: str = "incomplete",
        health: CapabilityHealth = CapabilityHealth.HEALTHY,
        health_issues: Iterable[str] = (),
        risk: CapabilityRisk = CapabilityRisk.LOW,
        risk_reasons: Iterable[str] = (),
    ) -> "CapabilityRecord":
        if not isinstance(kind, CapabilityKind):
            raise CapabilityValidationError("kind_invalid", "kind must be a CapabilityKind")
        if not isinstance(lifecycle, CapabilityLifecycle):
            raise CapabilityValidationError("lifecycle_invalid", "lifecycle must be a CapabilityLifecycle")
        if not isinstance(health, CapabilityHealth):
            raise CapabilityValidationError("health_invalid", "health must be a CapabilityHealth")
        if not isinstance(risk, CapabilityRisk):
            raise CapabilityValidationError("risk_invalid", "risk must be a CapabilityRisk")
        expected_prefix = f"{kind.value}:"
        if not capability_id.startswith(expected_prefix):
            raise CapabilityValidationError("capability_id_invalid", "capability ID kind does not match")
        identifier = capability_id[len(expected_prefix):]
        if not _IDENTIFIER_RE.fullmatch(identifier):
            raise CapabilityValidationError("capability_id_invalid", "capability ID is invalid")
        _validate_text(name, "name", maximum=256)
        _validate_text(description, "description", maximum=4096, empty=True)
        if version is not None:
            _validate_text(version, "version", maximum=64)
        normalized_path = _validate_relative_path(relative_path, "relative_path")
        normalized_entrypoint = None
        if entrypoint is not None:
            normalized_entrypoint = _validate_relative_path(entrypoint, "entrypoint")
        if compatibility_status not in _COMPATIBILITY_STATUSES:
            raise CapabilityValidationError("compatibility_status_invalid", "compatibility status is invalid")
        if provenance_status not in _PROVENANCE_STATUSES:
            raise CapabilityValidationError("provenance_status_invalid", "provenance status is invalid")
        if source_url is not None:
            _validate_text(source_url, "source_url", maximum=2048)
        if license_name is not None:
            _validate_text(license_name, "license", maximum=64)
        if sha256 is not None and not _SHA256_RE.fullmatch(sha256):
            raise CapabilityValidationError("sha256_invalid", "sha256 must be lowercase hexadecimal")

        compatibility_items = []
        for key, value in (compatibility or {}).items():
            _validate_text(key, "compatibility key", maximum=64)
            _validate_text(value, "compatibility value", maximum=128)
            compatibility_items.append((key, value))

        return cls(
            capability_id=capability_id,
            kind=kind,
            name=name,
            version=version,
            description=description,
            relative_path=normalized_path,
            entrypoint=normalized_entrypoint,
            lifecycle=lifecycle,
            permissions=_normalize_codes(permissions, "permission"),
            compatibility=tuple(sorted(set(compatibility_items))),
            compatibility_status=compatibility_status,
            source_url=source_url,
            license_name=license_name,
            sha256=sha256,
            provenance_status=provenance_status,
            health=health,
            health_issues=_normalize_codes(health_issues, "health issue"),
            risk=risk,
            risk_reasons=_normalize_codes(risk_reasons, "risk reason"),
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capability_id": self.capability_id,
            "kind": self.kind.value,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "relative_path": self.relative_path,
            "entrypoint": self.entrypoint,
            "lifecycle": self.lifecycle.value,
            "permissions": list(self.permissions),
            "compatibility": {
                "constraints": dict(self.compatibility),
                "status": self.compatibility_status,
            },
            "provenance": {
                "source_url": self.source_url,
                "license": self.license_name,
                "sha256": self.sha256,
                "status": self.provenance_status,
            },
            "health": {
                "status": self.health.value,
                "issues": list(self.health_issues),
            },
            "risk": {
                "level": self.risk.value,
                "reasons": list(self.risk_reasons),
            },
        }


@dataclass(frozen=True)
class CapabilitySnapshot:
    records: tuple[CapabilityRecord, ...]
    issues: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        records: Iterable[CapabilityRecord],
        issues: Iterable[str] = (),
    ) -> "CapabilitySnapshot":
        ordered = tuple(sorted(records, key=lambda record: record.capability_id))
        identifiers = [record.capability_id for record in ordered]
        if len(identifiers) != len(set(identifiers)):
            raise CapabilityValidationError("capability_duplicate", "capability IDs must be unique")
        return cls(records=ordered, issues=tuple(sorted(set(issues))))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capabilities": [record.to_public_dict() for record in self.records],
            "count": len(self.records),
            "issues": list(self.issues),
        }
