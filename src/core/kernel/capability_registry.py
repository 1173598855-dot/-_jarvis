"""Read-only discovery of repository-local capabilities."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.contracts.role_tool_catalog import (
    ROLE_TOOL_CATALOG,
    ROLE_TOOL_SOURCE_PATH,
    RoleToolAssembly,
)

from .capability_manifest import (
    CapabilityHealth,
    CapabilityKind,
    CapabilityLifecycle,
    CapabilityRecord,
    CapabilityRisk,
    CapabilitySnapshot,
    CapabilityValidationError,
)

_ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"}
_IGNORED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "venv",
}
_MAX_FILES = 512
_MAX_FILE_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 4 * 1024 * 1024
_MAX_CHILDREN = 1024
_MAX_TREE_ENTRIES = 8192


def _slugify(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._").lower()
    return value or "unknown"


def _extract_markdown_metadata(text: str, labels: Iterable[str]) -> Optional[str]:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"\*\*(?:{joined})\*\*\s*:\s*(?:\[[^\]]+\]\()?([^\s)]+)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _read_bounded_file(path: Path, *, code: str, message: str) -> bytes:
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise CapabilityValidationError(code, message)
    with path.open("rb") as handle:
        content = handle.read(_MAX_FILE_BYTES + 1)
    if len(content) > _MAX_FILE_BYTES:
        raise CapabilityValidationError(code, message)
    return content


def _bounded_sorted(
    values: Iterable,
    *,
    limit: int,
    key: Callable,
) -> tuple[list, int]:
    """Select the first sorted values without retaining the full input."""
    count = 0

    def counted_values():
        nonlocal count
        for value in values:
            count += 1
            yield value

    selected = heapq.nsmallest(limit, counted_values(), key=key)
    return selected, count


def _hash_files(files: list[tuple[str, Path]]) -> str:
    if len(files) > _MAX_FILES:
        raise CapabilityValidationError("tree_file_limit", "capability has too many files")
    total = 0
    digest = hashlib.sha256()
    for relative, path in sorted(files):
        content = _read_bounded_file(
            path,
            code="tree_file_too_large",
            message="capability file is too large",
        )
        size = len(content)
        total += size
        if total > _MAX_TOTAL_BYTES:
            raise CapabilityValidationError("tree_size_limit", "capability tree is too large")
        relative_bytes = relative.encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(4, "big"))
        digest.update(relative_bytes)
        digest.update(size.to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _hash_tree(root: Path) -> str:
    entry_count = 0
    file_count = 0
    directories = [root]

    def candidates():
        nonlocal entry_count, file_count
        while directories:
            directory = directories.pop()
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    candidate = Path(entry.path)
                    relative = candidate.relative_to(root)
                    if any(
                        part in _IGNORED_PARTS or part.startswith(".test-")
                        for part in relative.parts
                    ):
                        continue
                    if candidate.is_symlink():
                        raise CapabilityValidationError(
                            "symlink_rejected",
                            "capability contains a symlink",
                        )
                    if entry.is_dir(follow_symlinks=False):
                        entry_count += 1
                        if entry_count > _MAX_TREE_ENTRIES:
                            raise CapabilityValidationError(
                                "tree_entry_limit",
                                "capability has too many tree entries",
                            )
                        directories.append(candidate)
                    elif entry.is_file(follow_symlinks=False):
                        file_count += 1
                        if file_count > _MAX_FILES:
                            raise CapabilityValidationError(
                                "tree_file_limit",
                                "capability has too many files",
                            )
                        entry_count += 1
                        if entry_count > _MAX_TREE_ENTRIES:
                            raise CapabilityValidationError(
                                "tree_entry_limit",
                                "capability has too many tree entries",
                            )
                        yield (relative.as_posix(), candidate)

    files, count = _bounded_sorted(
        candidates(),
        limit=_MAX_FILES,
        key=lambda item: item[0],
    )
    if count > _MAX_FILES:
        raise CapabilityValidationError("tree_file_limit", "capability has too many files")
    return _hash_files(files)


def _hash_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CapabilityValidationError("entrypoint_invalid", "capability entrypoint is invalid")
    return _hash_files([(path.name, path)])


class CapabilityRegistry:
    """Discovers capabilities below fixed repository roots without executing them."""

    def __init__(
        self,
        repository_root: Path,
        *,
        cache_ttl_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        root = Path(repository_root)
        if root.is_symlink() or not root.is_dir():
            raise CapabilityValidationError("repository_root_invalid", "repository root is not trusted")
        if (
            isinstance(cache_ttl_seconds, bool)
            or not isinstance(cache_ttl_seconds, (int, float))
            or not math.isfinite(cache_ttl_seconds)
            or not 0.0 <= cache_ttl_seconds <= 60.0
        ):
            raise CapabilityValidationError(
                "cache_ttl_invalid",
                "cache TTL must be between zero and sixty seconds",
            )
        if not callable(clock):
            raise CapabilityValidationError("clock_invalid", "clock must be callable")
        self._root = root.resolve(strict=True)
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._clock = clock
        self._snapshot_lock = threading.Lock()
        self._cached_snapshot: Optional[CapabilitySnapshot] = None
        self._cached_at = 0.0

    def snapshot(self) -> CapabilitySnapshot:
        if self._cache_ttl_seconds == 0.0:
            return self._build_snapshot()

        with self._snapshot_lock:
            now = self._clock()
            if (
                self._cached_snapshot is not None
                and now >= self._cached_at
                and now - self._cached_at < self._cache_ttl_seconds
            ):
                return self._cached_snapshot
            snapshot = self._build_snapshot()
            self._cached_snapshot = snapshot
            self._cached_at = now
            return snapshot

    def _build_snapshot(self) -> CapabilitySnapshot:
        records = []
        issues = []
        self._discover_skills(records, issues)
        self._discover_plugins(records, issues)
        self._discover_role_tools(records, issues)
        self._discover_ui_components(records, issues)
        unique = []
        seen = set()
        for record in sorted(records, key=lambda item: (item.capability_id, item.relative_path)):
            if record.capability_id in seen:
                issues.append(f"capability_duplicate:{record.capability_id}")
                continue
            seen.add(record.capability_id)
            unique.append(record)
        return CapabilitySnapshot.create(unique, issues)

    def role_tool_assembly(self) -> RoleToolAssembly:
        """Return evidence only when registry records exactly match the catalog."""
        snapshot = self.snapshot()
        expected = {
            entry.capability_id: entry
            for entry in ROLE_TOOL_CATALOG
        }
        records = {
            record.capability_id: record
            for record in snapshot.records
            if record.kind is CapabilityKind.ROLE_TOOL
        }
        duplicate_issues = [
            issue for issue in snapshot.issues
            if issue.startswith("capability_duplicate:role_tool:")
        ]
        if duplicate_issues or set(records) != set(expected):
            raise CapabilityValidationError(
                "role_tool_assembly_invalid",
                "role tool capability records do not match the catalog",
            )
        for capability_id, entry in expected.items():
            record = records[capability_id]
            if (
                record.name != entry.definition.name
                or record.version is not None
                or record.description != entry.definition.description
                or record.relative_path != ROLE_TOOL_SOURCE_PATH
                or record.entrypoint != ROLE_TOOL_SOURCE_PATH
                or record.lifecycle is not CapabilityLifecycle.ENABLED
                or record.permissions != entry.permissions
                or record.compatibility != ()
                or record.compatibility_status != "unknown"
                or record.source_url is not None
                or record.license_name is not None
                or record.sha256 != entry.descriptor_sha256
                or record.provenance_status != "verified"
                or record.health is not CapabilityHealth.HEALTHY
                or record.health_issues != ()
                or record.risk is not CapabilityRisk.LOW
                or record.risk_reasons != ()
            ):
                raise CapabilityValidationError(
                    "role_tool_assembly_invalid",
                    "role tool capability record is not trusted",
                )
        return RoleToolAssembly.for_catalog()

    def _relative(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        try:
            return resolved.relative_to(self._root).as_posix()
        except ValueError as error:
            raise CapabilityValidationError("path_escape", "capability path escaped root") from error

    def _children(self, root: Path, kind: str, issues: list[str]):
        if not root.exists():
            return ()
        if root.is_symlink():
            issues.append(f"{kind}_root_symlink_rejected")
            return ()
        entries, count = _bounded_sorted(
            root.iterdir(),
            limit=_MAX_CHILDREN,
            key=lambda item: item.name.casefold(),
        )
        if count > _MAX_CHILDREN:
            issues.append(f"{kind}_child_limit")
        children = []
        for child in entries:
            if child.is_symlink():
                issues.append(f"{kind}_symlink_rejected:{child.name}")
                continue
            children.append(child)
        return tuple(children)

    def _discover_skills(self, records: list[CapabilityRecord], issues: list[str]) -> None:
        skills_root = self._root / "skills"
        for directory in self._children(skills_root, "skill", issues):
            if not directory.is_dir():
                continue
            skill_file = directory / "SKILL.md"
            if not skill_file.is_file() or skill_file.is_symlink():
                continue
            identifier = _slugify(directory.name)
            try:
                text = _read_bounded_file(
                    skill_file,
                    code="manifest_too_large",
                    message="SKILL.md is too large",
                ).decode("utf-8")
                heading = re.search(r"^#\s+([^\r\n]+)", text, flags=re.MULTILINE)
                name = directory.name
                description = ""
                if heading:
                    title = heading.group(1).strip()
                    name = re.split(r"\s+[—-]\s+", title, maxsplit=1)[0].strip() or directory.name
                    description = title[len(name):].lstrip(" -—")[:4096]
                source_url = _extract_markdown_metadata(text, ("来源", "Source"))
                license_name = _extract_markdown_metadata(text, ("许可证", "License"))
                digest = _hash_tree(directory)
                provenance_complete = bool(source_url and license_name in _ALLOWED_LICENSES)
                health_issues = () if provenance_complete else ("provenance_incomplete",)
                records.append(CapabilityRecord.create(
                    capability_id=f"skill:{identifier}",
                    kind=CapabilityKind.SKILL,
                    name=name,
                    version=None,
                    description=description,
                    relative_path=self._relative(directory),
                    entrypoint=self._relative(skill_file),
                    lifecycle=CapabilityLifecycle.DISCOVERED,
                    source_url=source_url,
                    license_name=license_name,
                    sha256=digest,
                    provenance_status="complete" if provenance_complete else "incomplete",
                    health=CapabilityHealth.HEALTHY if provenance_complete else CapabilityHealth.DEGRADED,
                    health_issues=health_issues,
                    risk=CapabilityRisk.LOW if provenance_complete else CapabilityRisk.MEDIUM,
                    risk_reasons=health_issues,
                ))
            except (OSError, UnicodeError, CapabilityValidationError) as error:
                issues.append(f"skill_invalid:{directory.name}:{getattr(error, 'code', 'read_failed')}")

    def _discover_plugins(self, records: list[CapabilityRecord], issues: list[str]) -> None:
        plugins_root = self._root / "plugins"
        for directory in self._children(plugins_root, "plugin", issues):
            if not directory.is_dir():
                continue
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file() or manifest_path.is_symlink():
                continue
            fallback_id = _slugify(directory.name)
            try:
                raw = _read_bounded_file(
                    manifest_path,
                    code="manifest_too_large",
                    message="manifest is too large",
                )
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise CapabilityValidationError("manifest_invalid", "manifest must be an object")
                plugin_id = data.get("plugin_id", fallback_id)
                if not isinstance(plugin_id, str):
                    raise CapabilityValidationError("manifest_invalid", "plugin_id must be a string")
                identifier = _slugify(plugin_id)
                name = data.get("name")
                version = data.get("version")
                entry_point = data.get("entry_point")
                if not all(isinstance(value, str) and value for value in (name, version, entry_point)):
                    raise CapabilityValidationError("manifest_invalid", "required plugin fields are invalid")
                entry_path = directory / entry_point
                health_issues = []
                if entry_path.is_symlink() or not entry_path.is_file():
                    health_issues.append("entrypoint_missing")
                digest = _hash_tree(directory)
                source_url = data.get("source_url") if isinstance(data.get("source_url"), str) else None
                license_name = data.get("license") if isinstance(data.get("license"), str) else None
                provenance_complete = bool(source_url and license_name in _ALLOWED_LICENSES)
                if not source_url:
                    health_issues.append("missing_source")
                if not license_name:
                    health_issues.append("missing_license")
                risk_reasons = list(health_issues)
                if data.get("runtime") == "native":
                    risk_reasons.append("native_runtime")
                invalid = "entrypoint_missing" in health_issues
                high_risk = invalid or "native_runtime" in risk_reasons
                permissions = data.get("permissions", [])
                if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
                    raise CapabilityValidationError("manifest_invalid", "permissions must be strings")
                compatibility = {}
                if isinstance(data.get("api_version"), str):
                    compatibility["jarvis_api"] = f"=={data['api_version']}"
                records.append(CapabilityRecord.create(
                    capability_id=f"plugin:{identifier}",
                    kind=CapabilityKind.PLUGIN,
                    name=name,
                    version=version,
                    description=data.get("description", "") if isinstance(data.get("description", ""), str) else "",
                    relative_path=self._relative(directory),
                    entrypoint=self._relative(entry_path),
                    lifecycle=CapabilityLifecycle.INVALID if invalid else CapabilityLifecycle.DISCOVERED,
                    permissions=permissions,
                    compatibility=compatibility,
                    source_url=source_url,
                    license_name=license_name,
                    sha256=digest,
                    provenance_status="complete" if provenance_complete else "incomplete",
                    health=CapabilityHealth.INVALID if invalid else (
                        CapabilityHealth.HEALTHY if not health_issues else CapabilityHealth.DEGRADED
                    ),
                    health_issues=health_issues,
                    risk=CapabilityRisk.HIGH if high_risk else (
                        CapabilityRisk.LOW if not risk_reasons else CapabilityRisk.MEDIUM
                    ),
                    risk_reasons=risk_reasons,
                ))
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                RecursionError,
                ValueError,
                CapabilityValidationError,
            ) as error:
                issue_code = getattr(error, "code", "manifest_invalid")
                if isinstance(error, json.JSONDecodeError):
                    issue_code = "manifest_invalid"
                records.append(CapabilityRecord.create(
                    capability_id=f"plugin:{fallback_id}",
                    kind=CapabilityKind.PLUGIN,
                    name=directory.name,
                    version=None,
                    description="",
                    relative_path=self._relative(directory),
                    entrypoint=None,
                    lifecycle=CapabilityLifecycle.INVALID,
                    provenance_status="incomplete",
                    health=CapabilityHealth.INVALID,
                    health_issues=(issue_code,),
                    risk=CapabilityRisk.HIGH,
                    risk_reasons=(issue_code,),
                ))

    def _discover_role_tools(
        self,
        records: list[CapabilityRecord],
        issues: list[str],
    ) -> None:
        source = self._root / ROLE_TOOL_SOURCE_PATH
        if source.is_symlink():
            issues.append("role_tool_source_symlink_rejected")
            return
        if not source.is_file():
            issues.append("role_tool_source_missing")
            return
        try:
            relative_source = self._relative(source)
            for entry in ROLE_TOOL_CATALOG:
                records.append(CapabilityRecord.create(
                    capability_id=entry.capability_id,
                    kind=CapabilityKind.ROLE_TOOL,
                    name=entry.definition.name,
                    version=None,
                    description=entry.definition.description,
                    relative_path=relative_source,
                    entrypoint=relative_source,
                    lifecycle=CapabilityLifecycle.ENABLED,
                    permissions=entry.permissions,
                    sha256=entry.descriptor_sha256,
                    provenance_status="verified",
                    health=CapabilityHealth.HEALTHY,
                    risk=CapabilityRisk.LOW,
                ))
        except (OSError, CapabilityValidationError) as error:
            issues.append(
                "role_tool_invalid:"
                f"{getattr(error, 'code', 'read_failed')}"
            )

    def _discover_ui_components(self, records: list[CapabilityRecord], issues: list[str]) -> None:
        components_root = self._root / "frontend" / "src" / "components"
        for candidate in self._children(components_root, "ui_component", issues):
            entrypoint = None
            name = candidate.stem
            if candidate.is_file() and candidate.suffix == ".tsx" and ".test." not in candidate.name:
                entrypoint = candidate
            elif candidate.is_dir():
                for filename in ("index.tsx", "index.ts"):
                    possible = candidate / filename
                    if possible.is_file() and not possible.is_symlink():
                        entrypoint = possible
                        name = candidate.name
                        break
            if entrypoint is None:
                continue
            identifier = _slugify(name)
            try:
                digest = _hash_tree(candidate) if candidate.is_dir() else _hash_file(entrypoint)
                records.append(CapabilityRecord.create(
                    capability_id=f"ui_component:{identifier}",
                    kind=CapabilityKind.UI_COMPONENT,
                    name=name,
                    version=None,
                    description="Local Solid.js UI component",
                    relative_path=self._relative(candidate),
                    entrypoint=self._relative(entrypoint),
                    lifecycle=CapabilityLifecycle.DISCOVERED,
                    sha256=digest,
                    provenance_status="incomplete",
                    health=CapabilityHealth.DEGRADED,
                    health_issues=("provenance_incomplete",),
                    risk=CapabilityRisk.MEDIUM,
                    risk_reasons=("provenance_incomplete",),
                ))
            except (OSError, CapabilityValidationError) as error:
                issues.append(f"ui_component_invalid:{candidate.name}:{getattr(error, 'code', 'read_failed')}")
