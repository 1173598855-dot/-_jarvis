"""Verified local capability bundles with no import or execution side effects."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import threading
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from core.kernel.capability_manifest import (
    SCHEMA_VERSION as CAPABILITY_SCHEMA_VERSION,
    CapabilityHealth,
    CapabilityKind,
    CapabilityLifecycle,
    CapabilityRecord,
    CapabilityRisk,
    CapabilityValidationError,
)


_ALLOWED_LICENSES = frozenset({
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
})
_EXPECTED_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "capability_id",
    "kind",
    "name",
    "version",
    "description",
    "source_url",
    "license",
    "entrypoint",
    "permissions",
    "compatibility",
})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPABILITY_ID_RE = re.compile(
    r"^(skill|plugin|ui_component):([a-z0-9][a-z0-9._-]{0,127})$"
)
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
})
_STORAGE_SEGMENT_SAFE = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")
_READ_CHUNK_BYTES = 64 * 1024
_STATE_SCHEMA_VERSION = 1
_MAX_INDEX_BYTES = 4 * 1024 * 1024
_ROOT_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[Path, threading.RLock] = {}


def _thread_lock_for(root: Path) -> threading.RLock:
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(root, threading.RLock())


class CapabilityStoreError(RuntimeError):
    """Stable package-store failure without archive or filesystem details."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class CapabilityPackageLimits:
    max_archive_bytes: int = 16 * 1024 * 1024
    max_files: int = 256
    max_file_bytes: int = 8 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024

    def __post_init__(self):
        for field_name in (
            "max_archive_bytes",
            "max_files",
            "max_file_bytes",
            "max_uncompressed_bytes",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.max_file_bytes > self.max_uncompressed_bytes:
            raise ValueError("max_file_bytes must not exceed max_uncompressed_bytes")


@dataclass(frozen=True, slots=True)
class InstalledCapability:
    """Immutable, public-safe state for one verified package revision."""

    record: CapabilityRecord
    revision_id: str
    bundle_sha256: str
    file_sha256: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if not isinstance(self.record, CapabilityRecord):
            raise ValueError("record must be a CapabilityRecord")
        if self.record.lifecycle is not CapabilityLifecycle.DISABLED:
            raise ValueError("installed capabilities must remain disabled")
        if self.record.schema_version != CAPABILITY_SCHEMA_VERSION:
            raise ValueError("capability record schema is unsupported")
        if not _SHA256_RE.fullmatch(self.revision_id):
            raise ValueError("revision_id must be a SHA-256 digest")
        if self.bundle_sha256 != self.revision_id or self.record.sha256 != self.bundle_sha256:
            raise ValueError("revision digests must match")
        expected_path = _revision_relative_path(self.record.capability_id, self.revision_id)
        if self.record.relative_path != expected_path:
            raise ValueError("revision path does not match its identity")
        normalized_files = []
        for path, digest in self.file_sha256:
            normalized_path = _safe_package_path(path)
            if normalized_path.endswith("/") or not _SHA256_RE.fullmatch(digest):
                raise ValueError("revision file metadata is invalid")
            normalized_files.append((normalized_path, digest))
        if tuple(sorted(set(normalized_files))) != self.file_sha256:
            raise ValueError("revision file metadata must be sorted and unique")
        file_paths = {path for path, _ in normalized_files}
        if (
            self.record.provenance_status != "verified"
            or not _is_safe_source_url(self.record.source_url)
            or self.record.license_name not in _ALLOWED_LICENSES
            or self.record.health is not CapabilityHealth.HEALTHY
            or self.record.health_issues
            or self.record.entrypoint not in file_paths
            or "capability.json" not in file_paths
            or not any(path.startswith("payload/") for path in file_paths)
            or any(
                path != "capability.json" and not path.startswith("payload/")
                for path in file_paths
            )
        ):
            raise ValueError("verified package metadata is invalid")

    @property
    def capability_id(self) -> str:
        return self.record.capability_id

    @property
    def kind(self) -> CapabilityKind:
        return self.record.kind

    @property
    def lifecycle(self) -> CapabilityLifecycle:
        return self.record.lifecycle

    @property
    def relative_path(self) -> str:
        return self.record.relative_path

    def to_public_dict(self) -> dict[str, object]:
        body = self.record.to_public_dict()
        body["revision"] = {
            "revision_id": self.revision_id,
            "bundle_sha256": self.bundle_sha256,
            "files": [
                {"path": path, "sha256": digest}
                for path, digest in self.file_sha256
            ],
        }
        return body

    def _to_state_dict(self) -> dict[str, object]:
        return {
            "schema_version": _STATE_SCHEMA_VERSION,
            "record_schema_version": self.record.schema_version,
            "capability_id": self.record.capability_id,
            "kind": self.record.kind.value,
            "name": self.record.name,
            "version": self.record.version,
            "description": self.record.description,
            "relative_path": self.record.relative_path,
            "entrypoint": self.record.entrypoint,
            "lifecycle": self.record.lifecycle.value,
            "permissions": list(self.record.permissions),
            "compatibility": dict(self.record.compatibility),
            "compatibility_status": self.record.compatibility_status,
            "source_url": self.record.source_url,
            "license": self.record.license_name,
            "provenance_status": self.record.provenance_status,
            "health": self.record.health.value,
            "health_issues": list(self.record.health_issues),
            "risk": self.record.risk.value,
            "risk_reasons": list(self.record.risk_reasons),
            "revision_id": self.revision_id,
            "bundle_sha256": self.bundle_sha256,
            "file_sha256": dict(self.file_sha256),
        }


@dataclass(frozen=True, slots=True)
class _VerifiedPackage:
    record: CapabilityRecord
    bundle_sha256: str
    file_sha256: tuple[tuple[str, str], ...]


def _reject_duplicate_keys(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    ).encode("utf-8")


def _safe_package_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "\\" in value
        or _DRIVE_PATH_RE.match(value)
        or any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
        raise ValueError("package path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value in {".", ".."}
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise ValueError("package path is invalid")
    _validate_portable_components(path)
    return path.as_posix()


def _validate_portable_components(path: PurePosixPath) -> None:
    for component in path.parts:
        try:
            encoded_length = len(component.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError("package path is invalid") from exc
        basename = component.split(".", 1)[0].upper()
        if (
            encoded_length > 255
            or component.endswith((" ", "."))
            or any(character in '<>:"|?*' for character in component)
            or basename in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError("package path is invalid")


def _capability_parts(capability_id: str) -> tuple[str, str]:
    if not isinstance(capability_id, str):
        raise ValueError("capability ID is invalid")
    match = _CAPABILITY_ID_RE.fullmatch(capability_id)
    if match is None:
        raise ValueError("capability ID is invalid")
    return match.group(1), match.group(2)


def _revision_relative_path(capability_id: str, revision_id: str) -> str:
    kind, identifier = _capability_parts(capability_id)
    if not isinstance(revision_id, str) or not _SHA256_RE.fullmatch(revision_id):
        raise ValueError("revision ID is invalid")
    storage_identifier = "".join(
        character
        if character in _STORAGE_SEGMENT_SAFE
        else f"~{ord(character):02x}"
        for character in identifier
    )
    return f"capabilities/{kind}/{storage_identifier}/revisions/{revision_id}"


def _is_safe_source_url(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if "\\" in value or any(character.isspace() or ord(character) < 32 for character in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.fragment == ""
        and (port is None or 1 <= port <= 65535)
    )


def _validate_member_name(info: zipfile.ZipInfo) -> str:
    name = info.orig_filename
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 1024
        or "\\" in name
        or _DRIVE_PATH_RE.match(name)
        or any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in name)
    ):
        raise CapabilityStoreError("ARCHIVE_PATH_INVALID", "archive path is invalid")
    if not (info.flag_bits & 0x800) and any(ord(character) > 127 for character in name):
        raise CapabilityStoreError(
            "ARCHIVE_NAME_ENCODING_INVALID",
            "archive names must use UTF-8",
        )

    path_value = name[:-1] if name.endswith("/") else name
    path = PurePosixPath(path_value)
    if (
        not path_value
        or path.is_absolute()
        or path_value in {".", ".."}
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != path_value
    ):
        raise CapabilityStoreError("ARCHIVE_PATH_INVALID", "archive path is invalid")
    try:
        _validate_portable_components(path)
    except ValueError as exc:
        raise CapabilityStoreError("ARCHIVE_PATH_INVALID", "archive path is invalid") from exc
    return path.as_posix() + ("/" if name.endswith("/") else "")


def _validate_entry_type(info: zipfile.ZipInfo) -> None:
    mode = info.external_attr >> 16
    entry_type = stat.S_IFMT(mode)
    if info.is_dir():
        if entry_type not in (0, stat.S_IFDIR):
            raise CapabilityStoreError(
                "ARCHIVE_ENTRY_TYPE_INVALID",
                "archive entry type is not allowed",
            )
        return
    if entry_type not in (0, stat.S_IFREG):
        raise CapabilityStoreError(
            "ARCHIVE_ENTRY_TYPE_INVALID",
            "archive entry type is not allowed",
        )


class FileCapabilityStore:
    """Validates trusted local ZIP bytes before any package publication."""

    def __init__(
        self,
        root: Path,
        limits: CapabilityPackageLimits | None = None,
    ) -> None:
        self._root = Path(root).absolute().resolve(strict=False)
        self._limits = limits or CapabilityPackageLimits()
        if not isinstance(self._limits, CapabilityPackageLimits):
            raise TypeError("limits must be CapabilityPackageLimits")
        self._thread_lock = _thread_lock_for(self._root)

    def install(self, bundle: bytes, expected_sha256: str) -> InstalledCapability:
        verified = self._verify_bundle(bundle, expected_sha256)
        installed = InstalledCapability(
            record=verified.record,
            revision_id=verified.bundle_sha256,
            bundle_sha256=verified.bundle_sha256,
            file_sha256=verified.file_sha256,
        )
        try:
            with self._thread_lock:
                index = self._load_index()
                existing = index["capabilities"].get(installed.capability_id)
                if existing is not None:
                    revisions = existing["revisions"]
                    if installed.revision_id not in revisions:
                        raise CapabilityStoreError(
                            "CAPABILITY_ALREADY_INSTALLED",
                            "a different package revision is already installed",
                        )
                    stored = self._load_revision(installed.capability_id, installed.revision_id)
                    if stored != installed:
                        raise CapabilityStoreError(
                            "REVISION_CONFLICT",
                            "stored revision metadata does not match the package",
                        )
                    return stored

                self._publish_revision(bundle, installed)
                index["capabilities"][installed.capability_id] = {
                    "selected_revision": installed.revision_id,
                    "revisions": [installed.revision_id],
                }
                self._write_index(index)
                return self._load_revision(installed.capability_id, installed.revision_id)
        except CapabilityStoreError:
            raise
        except OSError as exc:
            raise CapabilityStoreError("STORE_IO_ERROR", "capability store write failed") from exc

    def list_revisions(self, capability_id: str) -> tuple[InstalledCapability, ...]:
        try:
            _capability_parts(capability_id)
        except ValueError as exc:
            raise CapabilityStoreError("CAPABILITY_ID_INVALID", "capability ID is invalid") from exc
        try:
            with self._thread_lock:
                entry = self._load_index()["capabilities"].get(capability_id)
                if entry is None:
                    return ()
                return tuple(
                    self._load_revision(capability_id, revision_id)
                    for revision_id in entry["revisions"]
                )
        except CapabilityStoreError:
            raise
        except OSError as exc:
            raise CapabilityStoreError("STORE_IO_ERROR", "capability store read failed") from exc

    def _verify_bundle(self, bundle: bytes, expected_sha256: str) -> _VerifiedPackage:
        if not isinstance(bundle, bytes):
            raise CapabilityStoreError("ARCHIVE_INVALID", "bundle must be bytes")
        if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256):
            raise CapabilityStoreError("DIGEST_INVALID", "expected digest is invalid")

        actual_sha256 = hashlib.sha256(bundle).hexdigest()
        if actual_sha256 != expected_sha256:
            raise CapabilityStoreError("DIGEST_MISMATCH", "bundle digest does not match")
        if len(bundle) > self._limits.max_archive_bytes:
            raise CapabilityStoreError("ARCHIVE_SIZE_LIMIT", "archive exceeds its size limit")

        try:
            with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
                return self._verify_archive(archive, actual_sha256)
        except CapabilityStoreError:
            raise
        except UnicodeDecodeError as exc:
            raise CapabilityStoreError(
                "ARCHIVE_NAME_ENCODING_INVALID",
                "archive names must use UTF-8",
            ) from exc
        except (
            EOFError,
            NotImplementedError,
            RuntimeError,
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            zlib.error,
        ) as exc:
            raise CapabilityStoreError("ARCHIVE_INVALID", "archive cannot be read") from exc

    def _verify_archive(
        self,
        archive: zipfile.ZipFile,
        bundle_sha256: str,
    ) -> _VerifiedPackage:
        entries = archive.infolist()
        if len(entries) > self._limits.max_files:
            raise CapabilityStoreError("ARCHIVE_FILE_LIMIT", "archive has too many entries")

        names = []
        seen_names = set()
        total_declared = 0
        for info in entries:
            if info.flag_bits & 0x1:
                raise CapabilityStoreError("ARCHIVE_ENCRYPTED", "encrypted entries are not allowed")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise CapabilityStoreError(
                    "ARCHIVE_COMPRESSION_UNSUPPORTED",
                    "archive compression method is not allowed",
                )
            name = _validate_member_name(info)
            normalized_name = name.casefold()
            if normalized_name in seen_names:
                raise CapabilityStoreError(
                    "ARCHIVE_ENTRY_DUPLICATE",
                    "duplicate archive entries are not allowed",
                )
            seen_names.add(normalized_name)
            names.append(name)
            _validate_entry_type(info)
            if info.file_size < 0 or info.compress_size < 0:
                raise CapabilityStoreError("ARCHIVE_INVALID", "archive sizes are invalid")
            if not info.is_dir() and info.file_size > self._limits.max_file_bytes:
                raise CapabilityStoreError(
                    "ARCHIVE_FILE_SIZE_LIMIT",
                    "archive entry exceeds its size limit",
                )
            total_declared += info.file_size
            if total_declared > self._limits.max_uncompressed_bytes:
                raise CapabilityStoreError(
                    "ARCHIVE_EXPANDED_SIZE_LIMIT",
                    "archive exceeds its expanded size limit",
                )

        logical_entries = [
            (name.rstrip("/").casefold(), info.is_dir())
            for info, name in zip(entries, names)
        ]
        for index, (path, is_directory) in enumerate(logical_entries):
            for other_index, (other_path, other_is_directory) in enumerate(logical_entries):
                if index == other_index:
                    continue
                if path == other_path and is_directory != other_is_directory:
                    raise CapabilityStoreError(
                        "ARCHIVE_ENTRY_CONFLICT",
                        "archive entries have conflicting types",
                    )
                if not is_directory and other_path.startswith(path + "/"):
                    raise CapabilityStoreError(
                        "ARCHIVE_ENTRY_CONFLICT",
                        "archive entries have conflicting paths",
                    )

        self._validate_layout(entries, names)
        manifest_content = None
        total_read = 0
        digests = []
        for info, name in zip(entries, names):
            if info.is_dir():
                continue
            digest = hashlib.sha256()
            content = bytearray() if name == "capability.json" else None
            entry_read = 0
            with archive.open(info, "r") as source:
                while True:
                    chunk = source.read(_READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    entry_read += len(chunk)
                    total_read += len(chunk)
                    if entry_read > self._limits.max_file_bytes:
                        raise CapabilityStoreError(
                            "ARCHIVE_FILE_SIZE_LIMIT",
                            "archive entry exceeds its size limit",
                        )
                    if total_read > self._limits.max_uncompressed_bytes:
                        raise CapabilityStoreError(
                            "ARCHIVE_EXPANDED_SIZE_LIMIT",
                            "archive exceeds its expanded size limit",
                        )
                    digest.update(chunk)
                    if content is not None:
                        content.extend(chunk)
            digests.append((name, digest.hexdigest()))
            if content is not None:
                manifest_content = bytes(content)

        if manifest_content is None:
            raise CapabilityStoreError("MANIFEST_MISSING", "package manifest is required")
        record = self._parse_manifest(manifest_content, set(names), bundle_sha256)
        return _VerifiedPackage(
            record=record,
            bundle_sha256=bundle_sha256,
            file_sha256=tuple(sorted(digests)),
        )

    @staticmethod
    def _validate_layout(entries, names) -> None:
        manifest_count = 0
        payload_files = 0
        for info, name in zip(entries, names):
            if name == "capability.json" and not info.is_dir():
                manifest_count += 1
                continue
            if name == "payload/" and info.is_dir():
                continue
            if name.startswith("payload/"):
                if not info.is_dir():
                    payload_files += 1
                continue
            raise CapabilityStoreError(
                "ARCHIVE_LAYOUT_INVALID",
                "archive layout is invalid",
            )
        if manifest_count == 0:
            raise CapabilityStoreError("MANIFEST_MISSING", "package manifest is required")
        if payload_files == 0:
            raise CapabilityStoreError("PAYLOAD_MISSING", "package payload is required")

    @staticmethod
    def _parse_manifest(
        content: bytes,
        member_names: set[str],
        bundle_sha256: str,
    ) -> CapabilityRecord:
        try:
            manifest = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise CapabilityStoreError("MANIFEST_INVALID", "package manifest is invalid") from exc
        if (
            not isinstance(manifest, dict)
            or set(manifest) != _EXPECTED_MANIFEST_FIELDS
            or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
        ):
            raise CapabilityStoreError("MANIFEST_INVALID", "package manifest is invalid")

        source_url = manifest.get("source_url")
        if not _is_safe_source_url(source_url):
            raise CapabilityStoreError(
                "MANIFEST_SOURCE_INVALID",
                "package source URL is invalid",
            )
        license_name = manifest.get("license")
        if not isinstance(license_name, str) or license_name not in _ALLOWED_LICENSES:
            raise CapabilityStoreError(
                "MANIFEST_LICENSE_UNSUPPORTED",
                "package license is not allowed",
            )
        entrypoint = manifest.get("entrypoint")
        if (
            not isinstance(entrypoint, str)
            or not entrypoint.startswith("payload/")
            or entrypoint not in member_names
            or entrypoint.endswith("/")
        ):
            raise CapabilityStoreError(
                "MANIFEST_ENTRYPOINT_INVALID",
                "package entrypoint is invalid",
            )

        try:
            kind = CapabilityKind(manifest.get("kind"))
            capability_id = manifest.get("capability_id")
            version = manifest.get("version")
            permissions = manifest.get("permissions")
            compatibility = manifest.get("compatibility")
            if (
                not isinstance(capability_id, str)
                or not isinstance(version, str)
                or not version
                or not isinstance(permissions, list)
                or not isinstance(compatibility, Mapping)
            ):
                raise CapabilityValidationError("manifest_shape_invalid", "manifest shape is invalid")
            return CapabilityRecord.create(
                capability_id=capability_id,
                kind=kind,
                name=manifest.get("name"),
                version=version,
                description=manifest.get("description"),
                relative_path=_revision_relative_path(capability_id, bundle_sha256),
                entrypoint=entrypoint,
                lifecycle=CapabilityLifecycle.DISABLED,
                permissions=permissions,
                compatibility=compatibility,
                compatibility_status="unknown",
                source_url=source_url,
                license_name=license_name,
                sha256=bundle_sha256,
                provenance_status="verified",
                health=CapabilityHealth.HEALTHY,
                risk=CapabilityRisk.LOW,
            )
        except (CapabilityValidationError, TypeError, ValueError) as exc:
            raise CapabilityStoreError("MANIFEST_INVALID", "package manifest is invalid") from exc

    @property
    def _index_path(self) -> Path:
        return self._root / "index.json"

    def _load_index(self) -> dict[str, object]:
        if not self._index_path.exists():
            return {"schema_version": _STATE_SCHEMA_VERSION, "capabilities": {}}
        self._assert_store_path(self._index_path)
        if self._index_path.is_symlink() or not self._index_path.is_file():
            raise CapabilityStoreError("STORE_STATE_INVALID", "store index is invalid")
        content = self._read_bounded_state_file(self._index_path)
        try:
            value = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise CapabilityStoreError("STORE_STATE_INVALID", "store index is invalid") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "capabilities"}
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != _STATE_SCHEMA_VERSION
            or not isinstance(value.get("capabilities"), dict)
        ):
            raise CapabilityStoreError("STORE_STATE_INVALID", "store index is invalid")
        for capability_id, entry in value["capabilities"].items():
            try:
                _capability_parts(capability_id)
            except ValueError as exc:
                raise CapabilityStoreError("STORE_STATE_INVALID", "store index is invalid") from exc
            if not isinstance(entry, dict) or set(entry) != {"selected_revision", "revisions"}:
                raise CapabilityStoreError("STORE_STATE_INVALID", "store index is invalid")
            revisions = entry.get("revisions")
            selected_revision = entry.get("selected_revision")
            if (
                not isinstance(revisions, list)
                or not revisions
                or any(
                    not isinstance(revision, str) or not _SHA256_RE.fullmatch(revision)
                    for revision in revisions
                )
                or len(revisions) != len(set(revisions))
                or not isinstance(selected_revision, str)
                or selected_revision not in revisions
            ):
                raise CapabilityStoreError("STORE_STATE_INVALID", "store index is invalid")
        return value

    def _write_index(self, index: Mapping[str, object]) -> None:
        self._ensure_directory(self._root)
        temporary = self._root / f".index.{uuid4().hex}.tmp"
        try:
            self._write_file(temporary, _canonical_json(index))
            os.replace(temporary, self._index_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _publish_revision(self, bundle: bytes, installed: InstalledCapability) -> None:
        revision_path = self._root / Path(installed.relative_path)
        revisions_path = revision_path.parent
        self._ensure_directory(revisions_path)
        if revision_path.exists() or revision_path.is_symlink():
            stored = self._load_revision(installed.capability_id, installed.revision_id)
            if stored != installed:
                raise CapabilityStoreError(
                    "REVISION_CONFLICT",
                    "stored revision metadata does not match the package",
                )
            return

        staging = revisions_path / f".{installed.revision_id}.{uuid4().hex}.tmp"
        staging.mkdir()
        published = False
        try:
            expected_hashes = dict(installed.file_sha256)
            with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
                for info in archive.infolist():
                    name = _validate_member_name(info)
                    destination = staging.joinpath(*PurePosixPath(name.rstrip("/")).parts)
                    if info.is_dir():
                        self._ensure_directory(destination)
                        continue
                    self._ensure_directory(destination.parent)
                    digest = hashlib.sha256()
                    with archive.open(info, "r") as source, destination.open("xb") as target:
                        while True:
                            chunk = source.read(_READ_CHUNK_BYTES)
                            if not chunk:
                                break
                            target.write(chunk)
                            digest.update(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    if digest.hexdigest() != expected_hashes.get(name):
                        raise CapabilityStoreError(
                            "REVISION_CONFLICT",
                            "published content does not match verified content",
                        )
            self._write_file(staging / "bundle.zip", bundle)
            self._write_file(
                staging / "revision.json",
                _canonical_json(installed._to_state_dict()),
            )
            os.replace(staging, revision_path)
            published = True
        finally:
            if not published and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _load_revision(
        self,
        capability_id: str,
        revision_id: str,
    ) -> InstalledCapability:
        try:
            relative_path = _revision_relative_path(capability_id, revision_id)
        except ValueError as exc:
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid") from exc
        revision_path = self._root / Path(relative_path)
        state_path = revision_path / "revision.json"
        self._assert_store_path(revision_path)
        self._assert_store_path(state_path)
        if revision_path.is_symlink() or state_path.is_symlink() or not state_path.is_file():
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid")
        content = self._read_bounded_state_file(state_path)
        try:
            value = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
            installed = self._installed_from_state(value)
        except CapabilityStoreError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid") from exc
        if installed.capability_id != capability_id or installed.revision_id != revision_id:
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid")
        return installed

    @staticmethod
    def _installed_from_state(value: object) -> InstalledCapability:
        expected_fields = {
            "schema_version",
            "record_schema_version",
            "capability_id",
            "kind",
            "name",
            "version",
            "description",
            "relative_path",
            "entrypoint",
            "lifecycle",
            "permissions",
            "compatibility",
            "compatibility_status",
            "source_url",
            "license",
            "provenance_status",
            "health",
            "health_issues",
            "risk",
            "risk_reasons",
            "revision_id",
            "bundle_sha256",
            "file_sha256",
        }
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid")
        if (
            type(value.get("schema_version")) is not int
            or value.get("schema_version") != _STATE_SCHEMA_VERSION
            or type(value.get("record_schema_version")) is not int
            or value.get("record_schema_version") != CAPABILITY_SCHEMA_VERSION
        ):
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid")
        file_hashes = value.get("file_sha256")
        if (
            not isinstance(file_hashes, dict)
            or not isinstance(value.get("permissions"), list)
            or not isinstance(value.get("compatibility"), dict)
            or not isinstance(value.get("health_issues"), list)
            or not isinstance(value.get("risk_reasons"), list)
        ):
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid")
        try:
            record = CapabilityRecord.create(
                capability_id=value.get("capability_id"),
                kind=CapabilityKind(value.get("kind")),
                name=value.get("name"),
                version=value.get("version"),
                description=value.get("description"),
                relative_path=value.get("relative_path"),
                entrypoint=value.get("entrypoint"),
                lifecycle=CapabilityLifecycle(value.get("lifecycle")),
                permissions=value.get("permissions"),
                compatibility=value.get("compatibility"),
                compatibility_status=value.get("compatibility_status"),
                source_url=value.get("source_url"),
                license_name=value.get("license"),
                sha256=value.get("bundle_sha256"),
                provenance_status=value.get("provenance_status"),
                health=CapabilityHealth(value.get("health")),
                health_issues=value.get("health_issues"),
                risk=CapabilityRisk(value.get("risk")),
                risk_reasons=value.get("risk_reasons"),
            )
            return InstalledCapability(
                record=record,
                revision_id=value.get("revision_id"),
                bundle_sha256=value.get("bundle_sha256"),
                file_sha256=tuple(sorted(file_hashes.items())),
            )
        except (CapabilityValidationError, TypeError, ValueError) as exc:
            raise CapabilityStoreError("STORE_STATE_INVALID", "stored revision is invalid") from exc

    def _assert_store_path(self, path: Path) -> None:
        try:
            relative = path.relative_to(self._root)
            current = self._root
            for component in relative.parts:
                current = current / component
                try:
                    details = current.lstat()
                except FileNotFoundError:
                    break
                attributes = getattr(details, "st_file_attributes", 0)
                if stat.S_ISLNK(details.st_mode) or (
                    attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                ):
                    raise CapabilityStoreError(
                        "STORE_STATE_INVALID",
                        "store path contains a redirecting component",
                    )
            resolved = path.resolve(strict=False)
            resolved.relative_to(self._root)
        except CapabilityStoreError:
            raise
        except (OSError, ValueError) as exc:
            raise CapabilityStoreError(
                "STORE_STATE_INVALID",
                "store path leaves its trusted root",
            ) from exc

    def _read_bounded_state_file(self, path: Path) -> bytes:
        self._assert_store_path(path)
        try:
            if path.stat().st_size > _MAX_INDEX_BYTES:
                raise CapabilityStoreError("STORE_STATE_INVALID", "store state is too large")
            with path.open("rb") as handle:
                content = handle.read(_MAX_INDEX_BYTES + 1)
        except CapabilityStoreError:
            raise
        except OSError as exc:
            raise CapabilityStoreError("STORE_STATE_INVALID", "store state cannot be read") from exc
        if len(content) > _MAX_INDEX_BYTES:
            raise CapabilityStoreError("STORE_STATE_INVALID", "store state is too large")
        return content

    def _ensure_directory(self, path: Path) -> None:
        self._assert_store_path(path)
        if path.exists():
            if path.is_symlink() or not path.is_dir():
                raise CapabilityStoreError("STORE_STATE_INVALID", "store directory is invalid")
            return
        path.mkdir(parents=True, exist_ok=False)

    def _write_file(self, path: Path, content: bytes) -> None:
        self._assert_store_path(path)
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
