from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import threading
from typing import Any
from uuid import uuid4

from core.contracts.run_state import RunState, SCHEMA_VERSION
from core.kernel.secret_redaction import redact_text, redact_value


_FILE_NAMES = {
    "state": "state.json",
    "resume": "resume.md",
    "decisions": "decisions.jsonl",
    "events": "events.jsonl",
    "artifacts": "artifacts.json",
    "verification": "verification.json",
}
_ARCHIVE_MANIFEST_NAME = "archived-run.json"
_ROOT_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[Path, threading.RLock] = {}


def _thread_lock_for(root: Path) -> threading.RLock:
    with _ROOT_LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(root, threading.RLock())


def _supports_safe_fd_cleanup() -> bool:
    return (
        os.name != "nt"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.unlink in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
        and os.listdir in os.supports_fd
    )


def _windows_mutex_name(root: Path) -> str:
    canonical = os.path.normcase(
        os.path.normpath(str(root.resolve(strict=False)))
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return rf"Global\JARVIS.RunState.v1.{digest}"


@contextmanager
def _windows_named_mutex(root: Path):
    import ctypes
    from ctypes import wintypes

    create_mutex = ctypes.WinDLL("kernel32", use_last_error=True).CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    create_mutex.restype = wintypes.HANDLE
    wait_for_single_object = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    release_mutex = ctypes.WinDLL("kernel32", use_last_error=True).ReleaseMutex
    release_mutex.argtypes = [wintypes.HANDLE]
    release_mutex.restype = wintypes.BOOL
    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_mutex(None, False, _windows_mutex_name(root))
    if not handle:
        error = ctypes.get_last_error()
        raise RunStateIntegrityError("cannot create the repository mutex") from ctypes.WinError(
            error
        )

    acquired = False
    try:
        wait_result = wait_for_single_object(handle, 0xFFFFFFFF)
        if wait_result not in (0x00000000, 0x00000080):
            if wait_result == 0xFFFFFFFF:
                error = ctypes.get_last_error()
                cause = ctypes.WinError(error)
            else:
                cause = OSError(f"unexpected mutex wait result: {wait_result}")
            raise RunStateIntegrityError("cannot acquire the repository mutex") from cause
        acquired = True
        yield
    finally:
        release_error = None
        if acquired and not release_mutex(handle):
            release_error = ctypes.WinError(ctypes.get_last_error())
        close_error = None
        if not close_handle(handle):
            close_error = ctypes.WinError(ctypes.get_last_error())
        if release_error is not None:
            raise RunStateIntegrityError("cannot release the repository mutex") from release_error
        if close_error is not None:
            raise RunStateIntegrityError("cannot close the repository mutex") from close_error


class RunStateIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredRunState:
    state: RunState
    resume_markdown: str
    decisions: tuple[Mapping[str, Any], ...]
    events: tuple[Mapping[str, Any], ...]
    artifacts: Mapping[str, Any]
    verification: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _AuthenticatedActive:
    stored: StoredRunState
    manifest: Mapping[str, Any]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _document_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _is_reparse_point(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(details.st_mode):
        return True
    attributes = getattr(details, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


class FileRunStateRepository:
    def __init__(
        self,
        root: Path,
        key_provider: Callable[[], bytes | None],
    ) -> None:
        if not isinstance(root, Path):
            root = Path(root)
        self._root_input = root.absolute()
        self._root = self._root_input.resolve(strict=False)
        self._key_provider = key_provider
        self._thread_lock = _thread_lock_for(self._root)

    def save(
        self,
        state: RunState,
        resume_markdown: str,
        *,
        events: Iterable[Mapping[str, Any]] = (),
        decisions: Iterable[Mapping[str, Any]] = (),
        artifacts: Mapping[str, Any] | None = None,
        verification: Mapping[str, Any] | None = None,
    ) -> StoredRunState:
        if not isinstance(state, RunState):
            raise TypeError("state must be a RunState")
        if not isinstance(resume_markdown, str):
            raise TypeError("resume_markdown must be a string")
        key = self._require_key()
        self._ensure_directory(self._root)

        sanitized_state_value = redact_value(state.to_dict())
        sanitized_state = RunState.from_dict(sanitized_state_value)
        sanitized_resume = redact_text(resume_markdown)
        new_events = self._sanitize_records(events, "events")
        new_decisions = self._sanitize_records(decisions, "decisions")
        sanitized_artifacts = self._sanitize_mapping(artifacts or {}, "artifacts")
        sanitized_verification = self._sanitize_mapping(
            verification or {}, "verification"
        )

        with self._exclusive_write():
            return self._save_locked(
                key,
                sanitized_state,
                sanitized_resume,
                new_events,
                new_decisions,
                sanitized_artifacts,
                sanitized_verification,
            )

    def _save_locked(
        self,
        key: bytes,
        sanitized_state: RunState,
        sanitized_resume: str,
        new_events: tuple[Mapping[str, Any], ...],
        new_decisions: tuple[Mapping[str, Any], ...],
        sanitized_artifacts: dict[str, Any],
        sanitized_verification: dict[str, Any],
    ) -> StoredRunState:
        authenticated = (
            self._load_authenticated_active_locked()
            if self._active_path.exists()
            else None
        )
        existing = authenticated.stored if authenticated is not None else None
        request_artifacts = sanitized_artifacts
        request_verification = sanitized_verification
        expected_active = None
        if existing is not None:
            archive_path = self._archive_path(existing.state.run_id)
            if archive_path.exists() or _is_reparse_point(archive_path):
                raise RunStateIntegrityError("active run archive is pending")
            expected_active = (existing.state.run_id, existing.state.revision)
            if existing.state.run_id != sanitized_state.run_id:
                raise ValueError("archive the active run_id before saving another run")
            if sanitized_state.revision <= existing.state.revision:
                if (
                    sanitized_state.revision == existing.state.revision
                    and self._is_idempotent_retry(
                        authenticated.manifest,
                        sanitized_state,
                        sanitized_resume,
                        new_events,
                        new_decisions,
                        request_artifacts,
                        request_verification,
                    )
                ):
                    self._prune_revision_snapshots(
                        existing.state.run_id,
                        existing.state.revision,
                    )
                    return existing
                raise ValueError("revision must increase when updating an active run")
            all_events = existing.events + new_events
            all_decisions = existing.decisions + new_decisions
            if not sanitized_artifacts:
                sanitized_artifacts = dict(existing.artifacts)
            if not sanitized_verification:
                sanitized_verification = dict(existing.verification)
        else:
            all_events = new_events
            all_decisions = new_decisions

        run_directory = self._run_directory(sanitized_state.run_id)
        if (
            existing is None
            and run_directory.exists()
            and any(run_directory.iterdir())
            and not self._can_resume_unpublished_revision(
                run_directory,
                sanitized_state.revision,
            )
        ):
            raise ValueError("run_id already has archived or incomplete recovery data")
        self._ensure_directory(run_directory)

        contents = {
            "state": _document_json(sanitized_state.to_dict()),
            "resume": sanitized_resume.encode("utf-8"),
            "decisions": self._jsonl_bytes(all_decisions),
            "events": self._jsonl_bytes(all_events),
            "artifacts": _document_json(sanitized_artifacts),
            "verification": _document_json(sanitized_verification),
        }
        revision_directory = self._revision_directory(
            sanitized_state.run_id,
            sanitized_state.revision,
        )
        self._publish_revision(revision_directory, contents)

        manifest_files = {}
        for name, content in contents.items():
            path = revision_directory / _FILE_NAMES[name]
            manifest_files[name] = {
                "path": path.relative_to(self._root).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": sanitized_state.run_id,
            "revision": sanitized_state.revision,
            "files": manifest_files,
            "save_request": self._save_request_metadata(
                expected_active,
                sanitized_state,
                sanitized_resume,
                new_events,
                new_decisions,
                request_artifacts,
                request_verification,
            ),
        }
        manifest["hmac_sha256"] = hmac.new(
            key,
            _canonical_json(manifest),
            hashlib.sha256,
        ).hexdigest()
        self._assert_active_revision(expected_active)
        self._atomic_write(self._active_path, _document_json(manifest))

        stored = self._load_active_locked()
        if stored is None:
            raise RunStateIntegrityError("active manifest disappeared after save")
        self._prune_revision_snapshots(
            sanitized_state.run_id,
            sanitized_state.revision,
        )
        return stored

    def load_active(self) -> StoredRunState | None:
        if not self._root.exists():
            return None
        with self._exclusive_write():
            return self._load_active_locked()

    def _load_active_locked(self) -> StoredRunState | None:
        authenticated = self._load_authenticated_active_locked()
        return authenticated.stored if authenticated is not None else None

    def _load_authenticated_active_locked(self) -> _AuthenticatedActive | None:
        if not self._active_path.exists():
            return None
        key = self._require_key()
        manifest = self._read_json(self._active_path, "active manifest")
        expected_manifest_fields = {
            "schema_version",
            "run_id",
            "revision",
            "files",
            "hmac_sha256",
        }
        valid_manifest_fields = (
            expected_manifest_fields,
            expected_manifest_fields | {"save_request"},
        )
        if not isinstance(manifest, dict) or set(manifest) not in valid_manifest_fields:
            raise RunStateIntegrityError("active manifest schema is invalid")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise RunStateIntegrityError("active manifest schema_version is unsupported")
        signature = manifest.get("hmac_sha256")
        if not isinstance(signature, str):
            raise RunStateIntegrityError("active manifest HMAC is missing")
        unsigned = dict(manifest)
        unsigned.pop("hmac_sha256")
        expected_signature = hmac.new(
            key,
            _canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise RunStateIntegrityError("active manifest HMAC verification failed")

        run_id = manifest.get("run_id")
        revision = manifest.get("revision")
        if not isinstance(run_id, str):
            raise RunStateIntegrityError("active manifest run_id is invalid")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise RunStateIntegrityError("active manifest revision is invalid")
        if "save_request" in manifest:
            self._validate_save_request_metadata(
                manifest["save_request"],
                run_id,
                revision,
            )
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(_FILE_NAMES):
            raise RunStateIntegrityError("active manifest file set is invalid")

        entries: dict[str, dict[str, Any]] = {}
        manifest_paths: dict[str, object] = {}
        for name in _FILE_NAMES:
            entry = files.get(name)
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise RunStateIntegrityError(f"manifest entry for {name} is invalid")
            entries[name] = entry
            manifest_paths[name] = entry.get("path")

        legacy_directory = self._run_directory(run_id)
        revision_directory = self._revision_directory(run_id, revision)
        valid_path_sets = (
            {
                name: (legacy_directory / file_name)
                .relative_to(self._root)
                .as_posix()
                for name, file_name in _FILE_NAMES.items()
            },
            {
                name: (revision_directory / file_name)
                .relative_to(self._root)
                .as_posix()
                for name, file_name in _FILE_NAMES.items()
            },
        )
        if manifest_paths not in valid_path_sets:
            raise RunStateIntegrityError("active manifest file paths are invalid")

        loaded_bytes: dict[str, bytes] = {}
        for name in _FILE_NAMES:
            entry = entries[name]
            path = self._resolve_manifest_path(entry["path"])
            if not path.is_file():
                raise RunStateIntegrityError(f"recovery file for {name} is missing")
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if not isinstance(entry.get("sha256"), str) or not hmac.compare_digest(
                entry["sha256"], digest
            ):
                raise RunStateIntegrityError(f"recovery digest for {name} is invalid")
            loaded_bytes[name] = content

        state_value = self._decode_json_bytes(loaded_bytes["state"], "state")
        try:
            state = RunState.from_dict(state_value)
        except (TypeError, ValueError) as exc:
            raise RunStateIntegrityError("stored run state schema is invalid") from exc
        if state.run_id != run_id:
            raise RunStateIntegrityError("stored run_id does not match the manifest")
        if state.revision != revision:
            raise RunStateIntegrityError("stored revision does not match the manifest")

        try:
            resume_markdown = loaded_bytes["resume"].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RunStateIntegrityError("resume document is not valid UTF-8") from exc
        decisions = self._decode_jsonl(loaded_bytes["decisions"], "decisions")
        events = self._decode_jsonl(loaded_bytes["events"], "events")
        artifacts = self._decode_mapping(loaded_bytes["artifacts"], "artifacts")
        verification = self._decode_mapping(
            loaded_bytes["verification"], "verification"
        )
        return _AuthenticatedActive(
            stored=StoredRunState(
                state=state,
                resume_markdown=resume_markdown,
                decisions=decisions,
                events=events,
                artifacts=artifacts,
                verification=verification,
            ),
            manifest=manifest,
        )

    def archive_active(self, expected_run_id: str) -> None:
        with self._exclusive_write():
            authenticated = self._load_authenticated_active_locked()
            if authenticated is None:
                return
            stored = authenticated.stored
            if stored.state.run_id != expected_run_id:
                raise ValueError("expected run_id does not match the active run")
            archive_path = self._archive_path(stored.state.run_id)
            archive_content = _document_json(authenticated.manifest)
            self._prune_revision_snapshots(
                stored.state.run_id,
                stored.state.revision,
            )
            if archive_path.exists() or _is_reparse_point(archive_path):
                if _is_reparse_point(archive_path) or not archive_path.is_file():
                    raise RunStateIntegrityError("archived run manifest is invalid")
                try:
                    existing_archive = archive_path.read_bytes()
                except OSError as exc:
                    raise RunStateIntegrityError(
                        "archived run manifest is unreadable"
                    ) from exc
                if not hmac.compare_digest(existing_archive, archive_content):
                    raise RunStateIntegrityError(
                        "archived run manifest conflicts with the active run"
                    )
            else:
                self._atomic_write(archive_path, archive_content)
            self._active_path.unlink()

    @property
    def _active_path(self) -> Path:
        return self._root / "active-run.json"

    def _run_directory(self, run_id: str) -> Path:
        return self._root / "runs" / run_id

    def _revision_directory(self, run_id: str, revision: int) -> Path:
        return self._run_directory(run_id) / "revisions" / str(revision)

    def _archive_path(self, run_id: str) -> Path:
        return self._run_directory(run_id) / _ARCHIVE_MANIFEST_NAME

    def _require_key(self) -> bytes:
        try:
            key = self._key_provider()
        except Exception as exc:
            raise RunStateIntegrityError("integrity key provider failed") from exc
        if not isinstance(key, bytes) or len(key) < 32:
            raise RunStateIntegrityError(
                "active run requires an integrity key of at least 32 bytes"
            )
        return key

    def _save_request_metadata(
        self,
        expected_active: tuple[str, int] | None,
        state: RunState,
        resume_markdown: str,
        events: tuple[Mapping[str, Any], ...],
        decisions: tuple[Mapping[str, Any], ...],
        artifacts: Mapping[str, Any],
        verification: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected_value = self._expected_active_value(expected_active)
        request_value = {
            "expected_active": expected_value,
            "run_id": state.run_id,
            "revision": state.revision,
            "state": state.to_dict(),
            "resume_markdown": resume_markdown,
            "events": events,
            "decisions": decisions,
            "artifacts": artifacts,
            "verification": verification,
        }
        return {
            "expected_active": expected_value,
            "sha256": hashlib.sha256(_canonical_json(request_value)).hexdigest(),
        }

    def _is_idempotent_retry(
        self,
        manifest: Mapping[str, Any],
        state: RunState,
        resume_markdown: str,
        events: tuple[Mapping[str, Any], ...],
        decisions: tuple[Mapping[str, Any], ...],
        artifacts: Mapping[str, Any],
        verification: Mapping[str, Any],
    ) -> bool:
        metadata = manifest.get("save_request")
        if not isinstance(metadata, Mapping):
            return False
        expected_active = self._validate_save_request_metadata(
            metadata,
            state.run_id,
            state.revision,
        )
        actual = self._save_request_metadata(
            expected_active,
            state,
            resume_markdown,
            events,
            decisions,
            artifacts,
            verification,
        )
        return hmac.compare_digest(metadata["sha256"], actual["sha256"])

    @staticmethod
    def _expected_active_value(
        expected_active: tuple[str, int] | None,
    ) -> dict[str, Any] | None:
        if expected_active is None:
            return None
        return {
            "run_id": expected_active[0],
            "revision": expected_active[1],
        }

    @staticmethod
    def _validate_save_request_metadata(
        value: object,
        run_id: str,
        revision: int,
    ) -> tuple[str, int] | None:
        if not isinstance(value, Mapping) or set(value) != {
            "expected_active",
            "sha256",
        }:
            raise RunStateIntegrityError("active manifest save request is invalid")
        digest = value.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower():
            raise RunStateIntegrityError("active manifest save request digest is invalid")
        try:
            decoded_digest = bytes.fromhex(digest)
        except ValueError as exc:
            raise RunStateIntegrityError(
                "active manifest save request digest is invalid"
            ) from exc
        if len(decoded_digest) != 32:
            raise RunStateIntegrityError("active manifest save request digest is invalid")

        expected = value.get("expected_active")
        if expected is None:
            return None
        if not isinstance(expected, Mapping) or set(expected) != {"run_id", "revision"}:
            raise RunStateIntegrityError("active manifest save request base is invalid")
        expected_run_id = expected.get("run_id")
        expected_revision = expected.get("revision")
        if (
            expected_run_id != run_id
            or not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
            or expected_revision >= revision
        ):
            raise RunStateIntegrityError("active manifest save request base is invalid")
        return expected_run_id, expected_revision

    @contextmanager
    def _exclusive_write(self):
        with self._thread_lock:
            self._ensure_directory(self._root)
            if os.name == "nt":
                with _windows_named_mutex(self._root):
                    yield
                return

            if (
                not hasattr(os, "O_DIRECTORY")
                or not hasattr(os, "O_NOFOLLOW")
                or os.open not in os.supports_dir_fd
            ):
                raise RunStateIntegrityError(
                    "platform cannot safely open the repository lock"
                )

            import fcntl

            directory_flags = (
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0)
            )
            lock_flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0)
            )
            root_fd = os.open(self._root, directory_flags)
            try:
                lock_fd = os.open(
                    ".run-state.lock",
                    lock_flags,
                    0o600,
                    dir_fd=root_fd,
                )
                try:
                    if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                        raise RunStateIntegrityError(
                            "repository lock must be a regular file"
                        )
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
            finally:
                os.close(root_fd)

    def _assert_active_revision(
        self,
        expected: tuple[str, int] | None,
    ) -> None:
        stored = self._load_active_locked() if self._active_path.exists() else None
        actual = (
            None
            if stored is None
            else (stored.state.run_id, stored.state.revision)
        )
        if actual != expected:
            raise RunStateIntegrityError("active run changed while saving")

    @staticmethod
    def _can_resume_unpublished_revision(
        run_directory: Path,
        revision: int,
    ) -> bool:
        revisions = run_directory / "revisions"
        target = revisions / str(revision)
        try:
            run_children = tuple(run_directory.iterdir())
            revision_children = tuple(revisions.iterdir())
        except (FileNotFoundError, OSError):
            return False
        if (
            run_children != (revisions,)
            or _is_reparse_point(revisions)
            or not revisions.is_dir()
        ):
            return False
        for child in revision_children:
            if child == target:
                if _is_reparse_point(child) or not child.is_dir():
                    return False
                continue
            if not FileRunStateRepository._is_retry_staging_directory(
                child,
                revision,
            ):
                return False
        return True

    @staticmethod
    def _is_retry_staging_directory(path: Path, revision: int) -> bool:
        prefix = f".{revision}."
        suffix = ".staging"
        name = path.name
        if not name.startswith(prefix) or not name.endswith(suffix):
            return False
        token = name[len(prefix) : -len(suffix)]
        return (
            len(token) == 32
            and all(character in "0123456789abcdef" for character in token)
            and not _is_reparse_point(path)
            and path.is_dir()
        )

    def _ensure_directory(self, directory: Path) -> None:
        try:
            relative = directory.resolve(strict=False).relative_to(self._root)
        except ValueError as exc:
            raise RunStateIntegrityError("directory path escapes the repository root") from exc
        if not self._root.exists():
            self._root.mkdir(parents=True, exist_ok=True)
        if _is_reparse_point(self._root):
            raise RunStateIntegrityError("repository root cannot be a reparse point")
        current = self._root
        for part in relative.parts:
            current = current / part
            if current.exists():
                if _is_reparse_point(current):
                    raise RunStateIntegrityError("recovery path contains a reparse point")
                if not current.is_dir():
                    raise RunStateIntegrityError("recovery directory path is not a directory")
            else:
                current.mkdir()

    def _resolve_manifest_path(self, relative_value: object) -> Path:
        if not isinstance(relative_value, str) or not relative_value:
            raise RunStateIntegrityError("manifest path is invalid")
        relative = Path(relative_value)
        if relative.is_absolute():
            raise RunStateIntegrityError("manifest path must be relative")
        candidate = self._root / relative
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise RunStateIntegrityError("manifest path escapes the repository root") from exc
        current = self._root
        for part in relative.parts:
            current = current / part
            if current.exists() and _is_reparse_point(current):
                raise RunStateIntegrityError("manifest path contains a reparse point")
        return resolved

    def _prune_revision_snapshots(self, run_id: str, keep_revision: int) -> None:
        if not _supports_safe_fd_cleanup():
            return
        try:
            with self._open_repository_directory(
                "runs",
                run_id,
                "revisions",
            ) as revisions_fd:
                candidates = tuple(os.listdir(revisions_fd))
                for candidate in candidates:
                    if candidate == str(keep_revision):
                        continue
                    try:
                        revision = int(candidate)
                    except ValueError:
                        continue
                    if revision < 1 or str(revision) != candidate:
                        continue
                    self._discard_flat_directory(revisions_fd, candidate)
        except OSError:
            return

    @contextmanager
    def _open_repository_directory(self, *parts: str):
        flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptors = [os.open(self._root, flags)]
        try:
            for part in parts:
                if not part or part in {".", ".."} or Path(part).name != part:
                    raise RunStateIntegrityError(
                        "repository directory component is invalid"
                    )
                descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
            yield descriptors[-1]
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @staticmethod
    def _discard_flat_directory(parent_fd: int, directory_name: str) -> None:
        flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            directory_fd = os.open(
                directory_name,
                flags,
                dir_fd=parent_fd,
            )
        except OSError:
            return
        try:
            children = tuple(os.listdir(directory_fd))
            if not FileRunStateRepository._directory_entry_matches_fd(
                parent_fd,
                directory_name,
                directory_fd,
            ):
                return
            for child in children:
                if child not in _FILE_NAMES.values():
                    return
                details = os.stat(
                    child,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(details.st_mode):
                    return
            for child in children:
                if not FileRunStateRepository._directory_entry_matches_fd(
                    parent_fd,
                    directory_name,
                    directory_fd,
                ):
                    return
                os.unlink(child, dir_fd=directory_fd)
            if not FileRunStateRepository._directory_entry_matches_fd(
                parent_fd,
                directory_name,
                directory_fd,
            ):
                return
            os.rmdir(directory_name, dir_fd=parent_fd)
        except (FileNotFoundError, OSError):
            return
        finally:
            os.close(directory_fd)

    @staticmethod
    def _directory_entry_matches_fd(
        parent_fd: int,
        directory_name: str,
        directory_fd: int,
    ) -> bool:
        try:
            opened = os.fstat(directory_fd)
            current = os.stat(
                directory_name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except (FileNotFoundError, OSError):
            return False
        return (
            stat.S_ISDIR(current.st_mode)
            and opened.st_dev == current.st_dev
            and opened.st_ino == current.st_ino
        )

    def _atomic_write(self, path: Path, content: bytes) -> None:
        self._ensure_directory(path.parent)
        if path.exists() and _is_reparse_point(path):
            raise RunStateIntegrityError("refusing to replace a reparse-point recovery file")
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if path.read_bytes() != content:
                raise OSError(f"read-back verification failed for {path.name}")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _publish_revision(
        self,
        revision_directory: Path,
        contents: Mapping[str, bytes],
    ) -> None:
        if revision_directory.exists():
            self._verify_revision_contents(revision_directory, contents)
            return

        staging_directory = revision_directory.with_name(
            f".{revision_directory.name}.{uuid4().hex}.staging"
        )
        self._ensure_directory(staging_directory)
        published = False
        try:
            for name, content in contents.items():
                self._atomic_write(staging_directory / _FILE_NAMES[name], content)
            if revision_directory.exists():
                raise RunStateIntegrityError("revision recovery path already exists")
            os.replace(staging_directory, revision_directory)
            published = True
            self._verify_revision_contents(revision_directory, contents)
        finally:
            if not published:
                self._discard_staging_directory(staging_directory)

    def _verify_revision_contents(
        self,
        revision_directory: Path,
        contents: Mapping[str, bytes],
    ) -> None:
        self._ensure_directory(revision_directory)
        try:
            children = tuple(revision_directory.iterdir())
        except OSError as exc:
            raise RunStateIntegrityError("revision recovery directory is unreadable") from exc
        if {child.name for child in children} != set(_FILE_NAMES.values()):
            raise RunStateIntegrityError("revision recovery file set is invalid")
        for name, expected_content in contents.items():
            path = revision_directory / _FILE_NAMES[name]
            if _is_reparse_point(path) or not path.is_file():
                raise RunStateIntegrityError(
                    f"revision recovery file for {name} is invalid"
                )
            try:
                actual_content = path.read_bytes()
            except OSError as exc:
                raise RunStateIntegrityError(
                    f"revision recovery file for {name} is unreadable"
                ) from exc
            if not hmac.compare_digest(actual_content, expected_content):
                raise RunStateIntegrityError(
                    f"revision recovery file for {name} conflicts with the snapshot"
                )

    def _discard_staging_directory(self, staging_directory: Path) -> None:
        if not _supports_safe_fd_cleanup():
            return
        try:
            relative_parent = staging_directory.parent.relative_to(self._root)
        except ValueError:
            return
        try:
            with self._open_repository_directory(
                *relative_parent.parts,
            ) as parent_fd:
                self._discard_flat_directory(parent_fd, staging_directory.name)
        except OSError:
            return

    def _sanitize_records(
        self,
        records: Iterable[Mapping[str, Any]],
        field_name: str,
    ) -> tuple[Mapping[str, Any], ...]:
        result = []
        for record in records:
            if not isinstance(record, Mapping):
                raise TypeError(f"{field_name} entries must be mappings")
            sanitized = redact_value(record)
            if not isinstance(sanitized, Mapping):
                raise TypeError(f"{field_name} entries must remain mappings")
            _canonical_json(sanitized)
            result.append(dict(sanitized))
        return tuple(result)

    def _sanitize_mapping(
        self,
        value: Mapping[str, Any],
        field_name: str,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError(f"{field_name} must be a mapping")
        sanitized = redact_value(value)
        if not isinstance(sanitized, Mapping):
            raise TypeError(f"{field_name} must remain a mapping")
        _canonical_json(sanitized)
        return dict(sanitized)

    @staticmethod
    def _jsonl_bytes(records: tuple[Mapping[str, Any], ...]) -> bytes:
        if not records:
            return b""
        return b"\n".join(_canonical_json(record) for record in records) + b"\n"

    def _read_json(self, path: Path, field_name: str) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunStateIntegrityError(f"{field_name} is unreadable or invalid") from exc

    @staticmethod
    def _decode_json_bytes(content: bytes, field_name: str) -> object:
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunStateIntegrityError(f"{field_name} JSON is invalid") from exc

    def _decode_mapping(self, content: bytes, field_name: str) -> Mapping[str, Any]:
        value = self._decode_json_bytes(content, field_name)
        if not isinstance(value, dict):
            raise RunStateIntegrityError(f"{field_name} must contain a JSON object")
        return value

    def _decode_jsonl(
        self,
        content: bytes,
        field_name: str,
    ) -> tuple[Mapping[str, Any], ...]:
        if not content:
            return ()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RunStateIntegrityError(f"{field_name} JSONL is not UTF-8") from exc
        records = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RunStateIntegrityError(
                    f"{field_name} JSONL line {line_number} is invalid"
                ) from exc
            if not isinstance(value, dict):
                raise RunStateIntegrityError(
                    f"{field_name} JSONL line {line_number} is not an object"
                )
            records.append(value)
        return tuple(records)
