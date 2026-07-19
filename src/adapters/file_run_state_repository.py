from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
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

        existing = self.load_active() if self._active_path.exists() else None
        if existing is not None:
            if existing.state.run_id != sanitized_state.run_id:
                raise ValueError("archive the active run_id before saving another run")
            if sanitized_state.revision <= existing.state.revision:
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
        if existing is None and run_directory.exists() and any(run_directory.iterdir()):
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
        for name, content in contents.items():
            self._atomic_write(run_directory / _FILE_NAMES[name], content)

        manifest_files = {}
        for name, content in contents.items():
            path = run_directory / _FILE_NAMES[name]
            manifest_files[name] = {
                "path": path.relative_to(self._root).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": sanitized_state.run_id,
            "revision": sanitized_state.revision,
            "files": manifest_files,
        }
        manifest["hmac_sha256"] = hmac.new(
            key,
            _canonical_json(manifest),
            hashlib.sha256,
        ).hexdigest()
        self._atomic_write(self._active_path, _document_json(manifest))

        stored = self.load_active()
        if stored is None:
            raise RunStateIntegrityError("active manifest disappeared after save")
        return stored

    def load_active(self) -> StoredRunState | None:
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
        if not isinstance(manifest, dict) or set(manifest) != expected_manifest_fields:
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
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(_FILE_NAMES):
            raise RunStateIntegrityError("active manifest file set is invalid")

        loaded_bytes: dict[str, bytes] = {}
        for name, file_name in _FILE_NAMES.items():
            entry = files.get(name)
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise RunStateIntegrityError(f"manifest entry for {name} is invalid")
            expected_relative = (Path("runs") / run_id / file_name).as_posix()
            if entry.get("path") != expected_relative:
                raise RunStateIntegrityError(f"manifest path for {name} is invalid")
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
        return StoredRunState(
            state=state,
            resume_markdown=resume_markdown,
            decisions=decisions,
            events=events,
            artifacts=artifacts,
            verification=verification,
        )

    def archive_active(self, expected_run_id: str) -> None:
        stored = self.load_active()
        if stored is None:
            return
        if stored.state.run_id != expected_run_id:
            raise ValueError("expected run_id does not match the active run")
        self._active_path.unlink()

    @property
    def _active_path(self) -> Path:
        return self._root / "active-run.json"

    def _run_directory(self, run_id: str) -> Path:
        return self._root / "runs" / run_id

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
