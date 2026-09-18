from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

WORKER_PROTOCOL_VERSION = 1
MAX_WORKER_PROMPT_BYTES = 32 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class WorkerTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    CRASHED = "crashed"

    @property
    def is_terminal(self) -> bool:
        return self in {
            WorkerTaskStatus.SUCCEEDED,
            WorkerTaskStatus.FAILED,
            WorkerTaskStatus.TIMEOUT,
            WorkerTaskStatus.CANCELLED,
            WorkerTaskStatus.CRASHED,
        }


class WorkerEventKind(str, Enum):
    STARTED = "started"
    HEARTBEAT = "heartbeat"
    RESULT = "result"
    FAILURE = "failure"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


def _validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a canonical non-empty identifier")
    return value


def _validate_text(
    value: object,
    field_name: str,
    *,
    max_bytes: int | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if max_bytes is not None:
        try:
            encoded_length = len(value.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError(f"{field_name} must be valid UTF-8") from exc
        if encoded_length > max_bytes:
            raise ValueError(
                f"{field_name} exceeds the {max_bytes}-byte limit"
            )
    return value


def _validate_timeout(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= 300
    ):
        raise ValueError("timeout_seconds must be an integer from 1 through 300")
    return value


def _strict_mapping(
    value: object,
    expected: set[str],
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing {sorted(missing)}")
        if unknown:
            parts.append(f"unknown {sorted(unknown)}")
        raise ValueError(f"{field_name} has {'; '.join(parts)}")
    return value


@dataclass(frozen=True, slots=True)
class WorkerTaskRequest:
    protocol_version: int
    task_id: str
    attempt_id: str
    role_name: str
    prompt: str
    timeout_seconds: int
    created_at: str

    def __post_init__(self) -> None:
        if self.protocol_version != WORKER_PROTOCOL_VERSION:
            raise ValueError(
                f"protocol_version must be {WORKER_PROTOCOL_VERSION}"
            )
        _validate_identifier(self.task_id, "task_id")
        _validate_identifier(self.attempt_id, "attempt_id")
        _validate_identifier(self.role_name, "role_name")
        _validate_text(
            self.prompt,
            "prompt",
            max_bytes=MAX_WORKER_PROMPT_BYTES,
        )
        _validate_timeout(self.timeout_seconds)
        _validate_timestamp(self.created_at, "created_at")

    @classmethod
    def new(
        cls,
        role_name: str,
        prompt: str,
        timeout_seconds: int,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
    ) -> WorkerTaskRequest:
        return cls(
            protocol_version=WORKER_PROTOCOL_VERSION,
            task_id=task_id or f"task-{uuid.uuid4().hex}",
            attempt_id=attempt_id or f"attempt-{uuid.uuid4().hex}",
            role_name=role_name,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            created_at=_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "role_name": self.role_name,
            "prompt": self.prompt,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: object) -> WorkerTaskRequest:
        fields = {
            "protocol_version",
            "task_id",
            "attempt_id",
            "role_name",
            "prompt",
            "timeout_seconds",
            "created_at",
        }
        raw = _strict_mapping(value, fields, "worker request")
        return cls(**{field: raw[field] for field in fields})


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    protocol_version: int
    task_id: str
    attempt_id: str
    sequence: int
    kind: WorkerEventKind
    timestamp: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.protocol_version != WORKER_PROTOCOL_VERSION:
            raise ValueError(
                f"protocol_version must be {WORKER_PROTOCOL_VERSION}"
            )
        _validate_identifier(self.task_id, "task_id")
        _validate_identifier(self.attempt_id, "attempt_id")
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 1
        ):
            raise ValueError("sequence must be a positive integer")
        if not isinstance(self.kind, WorkerEventKind):
            raise ValueError("kind must be a WorkerEventKind")
        _validate_timestamp(self.timestamp, "timestamp")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")

    @classmethod
    def new(
        cls,
        request: WorkerTaskRequest,
        *,
        sequence: int,
        kind: WorkerEventKind,
        payload: Mapping[str, Any],
    ) -> WorkerEvent:
        return cls(
            protocol_version=WORKER_PROTOCOL_VERSION,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            sequence=sequence,
            kind=kind,
            timestamp=_now(),
            payload=dict(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, value: object) -> WorkerEvent:
        fields = {
            "protocol_version",
            "task_id",
            "attempt_id",
            "sequence",
            "kind",
            "timestamp",
            "payload",
        }
        raw = _strict_mapping(value, fields, "worker event")
        try:
            kind = WorkerEventKind(raw["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("worker event kind is unsupported") from exc
        return cls(
            protocol_version=raw["protocol_version"],
            task_id=raw["task_id"],
            attempt_id=raw["attempt_id"],
            sequence=raw["sequence"],
            kind=kind,
            timestamp=raw["timestamp"],
            payload=raw["payload"],
        )


@dataclass(frozen=True, slots=True)
class WorkerTaskRecord:
    protocol_version: int
    task_id: str
    attempt_id: str
    role_name: str
    status: WorkerTaskStatus
    created_at: str
    updated_at: str
    timeout_seconds: int
    result: Any = None
    error: str = ""
    worker_pid: int | None = None
    last_heartbeat: str | None = None
    last_event_sequence: int = 0
    termination_confirmed: bool = False

    def __post_init__(self) -> None:
        if self.protocol_version != WORKER_PROTOCOL_VERSION:
            raise ValueError(
                f"protocol_version must be {WORKER_PROTOCOL_VERSION}"
            )
        _validate_identifier(self.task_id, "task_id")
        _validate_identifier(self.attempt_id, "attempt_id")
        _validate_identifier(self.role_name, "role_name")
        if not isinstance(self.status, WorkerTaskStatus):
            raise ValueError("status must be a WorkerTaskStatus")
        _validate_timestamp(self.created_at, "created_at")
        _validate_timestamp(self.updated_at, "updated_at")
        _validate_timeout(self.timeout_seconds)
        if not isinstance(self.error, str):
            raise ValueError("error must be a string")
        if self.worker_pid is not None and (
            not isinstance(self.worker_pid, int)
            or isinstance(self.worker_pid, bool)
            or self.worker_pid <= 0
        ):
            raise ValueError("worker_pid must be a positive integer or null")
        if self.last_heartbeat is not None:
            _validate_timestamp(self.last_heartbeat, "last_heartbeat")
        if (
            not isinstance(self.last_event_sequence, int)
            or isinstance(self.last_event_sequence, bool)
            or self.last_event_sequence < 0
        ):
            raise ValueError("last_event_sequence must be a non-negative integer")
        if not isinstance(self.termination_confirmed, bool):
            raise ValueError("termination_confirmed must be a boolean")
        if self.status in {
            WorkerTaskStatus.TIMEOUT,
            WorkerTaskStatus.CANCELLED,
        } and not self.termination_confirmed:
            raise ValueError(
                "termination_confirmed is required for timeout or cancelled status"
            )

    @classmethod
    def from_request(cls, request: WorkerTaskRequest) -> WorkerTaskRecord:
        return cls(
            protocol_version=WORKER_PROTOCOL_VERSION,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            role_name=request.role_name,
            status=WorkerTaskStatus.QUEUED,
            created_at=request.created_at,
            updated_at=request.created_at,
            timeout_seconds=request.timeout_seconds,
        )

    def evolve(self, **changes: object) -> WorkerTaskRecord:
        if self.status.is_terminal:
            raise ValueError("terminal worker task records cannot transition")
        if "updated_at" in changes:
            raise ValueError("updated_at is managed by WorkerTaskRecord.evolve")
        return replace(self, **changes, updated_at=_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "role_name": self.role_name,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "timeout_seconds": self.timeout_seconds,
            "result": self.result,
            "error": self.error,
            "worker_pid": self.worker_pid,
            "last_heartbeat": self.last_heartbeat,
            "last_event_sequence": self.last_event_sequence,
            "termination_confirmed": self.termination_confirmed,
        }

    @classmethod
    def from_dict(cls, value: object) -> WorkerTaskRecord:
        fields = {
            "protocol_version",
            "task_id",
            "attempt_id",
            "role_name",
            "status",
            "created_at",
            "updated_at",
            "timeout_seconds",
            "result",
            "error",
            "worker_pid",
            "last_heartbeat",
            "last_event_sequence",
            "termination_confirmed",
        }
        raw = _strict_mapping(value, fields, "worker task record")
        try:
            status = WorkerTaskStatus(raw["status"])
        except (TypeError, ValueError) as exc:
            raise ValueError("worker task status is unsupported") from exc
        values = {field: raw[field] for field in fields if field != "status"}
        return cls(status=status, **values)
