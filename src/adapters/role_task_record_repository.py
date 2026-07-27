from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from core.contracts.worker_protocol import WorkerTaskRecord


_ROLE_TASK_RECORDS_NAME = "role-tasks.json"


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
            tmp.write_text(
                json.dumps(records, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _read(self) -> list[dict[str, Any]]:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("role-tasks.json root must be a JSON array")
        return raw
