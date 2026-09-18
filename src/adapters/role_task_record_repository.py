from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from core.contracts.worker_protocol import WorkerTaskRecord

_ROLE_TASK_RECORDS_NAME = "role-tasks.json"
_MAX_ROLE_TASK_RECORD_FILE_BYTES = 8 * 1024 * 1024


def _read_bounded_bytes(path: Path) -> bytes:
    if path.stat().st_size > _MAX_ROLE_TASK_RECORD_FILE_BYTES:
        raise ValueError("role-task snapshot exceeds its size limit")
    with path.open("rb") as handle:
        content = handle.read(_MAX_ROLE_TASK_RECORD_FILE_BYTES + 1)
    if len(content) > _MAX_ROLE_TASK_RECORD_FILE_BYTES:
        raise ValueError("role-task snapshot exceeds its size limit")
    return content


def _encode_bounded_json(value: object) -> bytes:
    encoder = json.JSONEncoder(ensure_ascii=False, default=str)
    chunks: list[str] = []
    encoded_bytes = 0
    for chunk in encoder.iterencode(value):
        encoded_bytes += len(chunk.encode("utf-8"))
        if encoded_bytes > _MAX_ROLE_TASK_RECORD_FILE_BYTES:
            raise ValueError("role-task snapshot exceeds its size limit")
        chunks.append(chunk)
    return "".join(chunks).encode("utf-8")


class RoleTaskRecordRepository:
    """Persists WorkerTaskRecord snapshots so they survive process restarts.

    Records are serialised to a single JSON array file inside *root*,
    the same directory convention used by FileRunStateRepository.
    Thread-safe for concurrent read/write via an RLock.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.absolute()
        self._path = self._root / _ROLE_TASK_RECORDS_NAME
        self._lock = threading.RLock()

    def save(self, records: list[WorkerTaskRecord]) -> None:
        """Atomically replace the persisted records with *records*."""
        raw = [r.to_dict() for r in records]
        with self._lock:
            self._write(raw)

    def load(self) -> list[WorkerTaskRecord]:
        """Return all persisted records, or an empty list if none exist."""
        with self._lock:
            if not self._path.is_file():
                return []
            try:
                raw = self._read()
            except (OSError, json.JSONDecodeError, ValueError):
                return []
            result: list[WorkerTaskRecord] = []
            for item in raw:
                try:
                    result.append(WorkerTaskRecord.from_dict(item))
                except (ValueError, TypeError, KeyError):
                    continue
            return result

    def clear(self) -> None:
        """Remove the persisted record file if it exists."""
        with self._lock:
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                pass

    @property
    def path(self) -> Path:
        return self._path

    def _write(self, records: list[dict[str, Any]]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_bytes(_encode_bounded_json(records))
            tmp.replace(self._path)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _read(self) -> list[dict[str, Any]]:
        raw = json.loads(_read_bounded_bytes(self._path).decode("utf-8"))
        if not isinstance(raw, list):
            raise ValueError("role-tasks.json root must be a JSON array")
        return raw
