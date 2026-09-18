"""Static-runner process adapter for opt-in generic Orchestrator agents."""

from __future__ import annotations

import importlib
import json
import math
import os
import re
import sys
import threading
import time
import types
import uuid
from collections.abc import Mapping
from typing import Any

from core.brain.role_worker import RoleWorkerSupervisor, WorkerTaskTerminalError
from core.contracts.worker_protocol import WorkerTaskRecord, WorkerTaskRequest

MAX_DECLARED_TASK_BYTES = 32 * 1024
MAX_DECLARED_DELAY_MILLISECONDS = 300_000
MAX_DECLARED_JSON_DEPTH = 64
MAX_DECLARED_INTEGER_DIGITS = 512
_MAX_DECLARED_INTEGER_MAGNITUDE = 10 ** MAX_DECLARED_INTEGER_DIGITS
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class DeclaredAgentTaskError(ValueError):
    """Raised before process creation when a declared task is unsafe to encode."""


class _JsonNormalizationBudget:
    """Bound metadata traversal before it can be copied into a new JSON value."""

    def __init__(self) -> None:
        self._encoded_bytes = 0

    def consume(self, encoded_bytes: int) -> None:
        self._encoded_bytes += encoded_bytes
        if self._encoded_bytes > MAX_DECLARED_TASK_BYTES:
            raise DeclaredAgentTaskError(
                f"Declared agent task exceeds {MAX_DECLARED_TASK_BYTES} bytes"
            )


def _json_string_byte_length(value: str, field_name: str) -> int:
    """Validate UTF-8 text and return its exact JSON string byte length."""
    if type(value) is not str:
        raise DeclaredAgentTaskError(f"{field_name} must be a plain string")
    if len(value) > MAX_DECLARED_TASK_BYTES:
        raise DeclaredAgentTaskError(
            f"{field_name} exceeds {MAX_DECLARED_TASK_BYTES} bytes"
        )

    encoded_length = 2
    for character in value:
        code_point = ord(character)
        if 0xD800 <= code_point <= 0xDFFF:
            raise DeclaredAgentTaskError(
                f"{field_name} must not contain invalid Unicode"
            )
        if character in {'"', "\\"}:
            encoded_length += 2
        elif code_point <= 0x1F:
            encoded_length += 2 if character in {"\b", "\t", "\n", "\f", "\r"} else 6
        elif code_point <= 0x7F:
            encoded_length += 1
        elif code_point <= 0x7FF:
            encoded_length += 2
        elif code_point <= 0xFFFF:
            encoded_length += 3
        else:
            encoded_length += 4
    return encoded_length


def _validate_utf8_string(value: str, field_name: str) -> str:
    _json_string_byte_length(value, field_name)
    return value


def _normalize_json_value(
    value: object,
    field_name: str,
    *,
    depth: int = 0,
    active_containers: set[int] | None = None,
    budget: _JsonNormalizationBudget | None = None,
) -> Any:
    """Return a strict JSON value without preserving mutable input containers."""
    if depth > MAX_DECLARED_JSON_DEPTH:
        raise DeclaredAgentTaskError(
            f"{field_name} exceeds JSON nesting depth"
        )
    if budget is None:
        budget = _JsonNormalizationBudget()

    if value is None:
        budget.consume(4)
        return value
    if type(value) is bool:
        budget.consume(4 if value else 5)
        return value
    if type(value) is str:
        budget.consume(_json_string_byte_length(value, field_name))
        return value
    if type(value) is int:
        if (
            value >= _MAX_DECLARED_INTEGER_MAGNITUDE
            or value <= -_MAX_DECLARED_INTEGER_MAGNITUDE
        ):
            raise DeclaredAgentTaskError(
                f"{field_name} exceeds integer digit limit"
            )
        budget.consume(len(str(value)))
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise DeclaredAgentTaskError(
                f"{field_name} must not contain non-finite numbers"
            )
        budget.consume(len(repr(value)))
        return value

    if active_containers is None:
        active_containers = set()
    if type(value) is dict:
        container_id = id(value)
        if container_id in active_containers:
            raise DeclaredAgentTaskError(
                f"{field_name} must not contain recursive values"
            )
        active_containers.add(container_id)
        try:
            normalized: dict[str, Any] = {}
            budget.consume(2)
            for index, (key, item) in enumerate(value.items()):
                if index:
                    budget.consume(1)
                if type(key) is not str:
                    raise DeclaredAgentTaskError(
                        f"{field_name} object keys must be strings"
                    )
                budget.consume(
                    _json_string_byte_length(key, f"{field_name} object key") + 1
                )
                if key in normalized:
                    raise DeclaredAgentTaskError(
                        f"{field_name} object keys must be unique"
                    )
                normalized[key] = _normalize_json_value(
                    item,
                    field_name,
                    depth=depth + 1,
                    active_containers=active_containers,
                    budget=budget,
                )
            return normalized
        finally:
            active_containers.remove(container_id)

    if type(value) in (list, tuple):
        container_id = id(value)
        if container_id in active_containers:
            raise DeclaredAgentTaskError(
                f"{field_name} must not contain recursive values"
            )
        active_containers.add(container_id)
        try:
            budget.consume(2)
            normalized_list: list[Any] = []
            for index, item in enumerate(value):
                if index:
                    budget.consume(1)
                normalized_list.append(
                    _normalize_json_value(
                        item,
                        field_name,
                        depth=depth + 1,
                        active_containers=active_containers,
                        budget=budget,
                    )
                )
            return normalized_list
        finally:
            active_containers.remove(container_id)

    raise DeclaredAgentTaskError(
        f"{field_name} contains an unsupported JSON value"
    )


def _encode_bounded_json(value: object) -> str:
    try:
        chunks: list[str] = []
        encoded_length = 0
        encoder = json.JSONEncoder(
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        for chunk in encoder.iterencode(value):
            encoded_length += len(chunk.encode("utf-8"))
            if encoded_length > MAX_DECLARED_TASK_BYTES:
                raise DeclaredAgentTaskError(
                    f"Declared agent task exceeds {MAX_DECLARED_TASK_BYTES} bytes"
                )
            chunks.append(chunk)
        return "".join(chunks)
    except DeclaredAgentTaskError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise DeclaredAgentTaskError(
            "Declared agent task must be JSON-serializable"
        ) from exc


def _reject_json_constant(_value: str) -> None:
    raise ValueError("Declared agent worker task contains an invalid JSON constant")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Declared agent worker task contains duplicate JSON keys")
        value[key] = item
    return value


def _validate_identifier(value: object, field_name: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise DeclaredAgentTaskError(
            f"{field_name} must be a canonical non-empty identifier"
        )
    return value


def _validate_timeout(value: object) -> int:
    if (
        type(value) is not int
        or not 1 <= value <= 300
    ):
        raise DeclaredAgentTaskError(
            "timeout must be an integer from 1 through 300"
        )
    return value


def _validate_priority(value: object) -> int:
    if (
        type(value) is not int
        or not 0 <= value <= 3
    ):
        raise DeclaredAgentTaskError("priority must be an integer from 0 through 3")
    return value


def _task_encoding_budget(
    task_id: str,
    agent_name: str,
    prompt: str,
    timeout: int,
    priority: int,
) -> _JsonNormalizationBudget:
    """Start an exact byte budget for the complete encoded task object."""
    budget = _JsonNormalizationBudget()
    fields: tuple[tuple[str, int | None], ...] = (
        ("task_id", _json_string_byte_length(task_id, "task_id")),
        ("agent_name", _json_string_byte_length(agent_name, "agent_name")),
        ("prompt", _json_string_byte_length(prompt, "prompt")),
        ("timeout", len(str(timeout))),
        ("priority", len(str(priority))),
        ("metadata", None),
    )
    budget.consume(2)
    for index, (key, value_length) in enumerate(fields):
        if index:
            budget.consume(1)
        budget.consume(_json_string_byte_length(key, "task field") + 1)
        if value_length is not None:
            budget.consume(value_length)
    return budget


def _encode_task(
    *,
    task_id: object,
    agent_name: object,
    prompt: object,
    timeout: object,
    priority: object,
    metadata: object,
) -> str:
    if type(task_id) is not str or not task_id:
        raise DeclaredAgentTaskError("task_id must be a non-empty string")
    _validate_utf8_string(task_id, "task_id")
    name = _validate_identifier(agent_name, "agent_name")
    if type(prompt) is not str:
        raise DeclaredAgentTaskError("prompt must be a non-empty string")
    _validate_utf8_string(prompt, "prompt")
    if not prompt.strip():
        raise DeclaredAgentTaskError("prompt must be a non-empty string")
    timeout_seconds = _validate_timeout(timeout)
    task_priority = _validate_priority(priority)
    if type(metadata) is not dict:
        raise DeclaredAgentTaskError("metadata must be an object")

    try:
        normalized_metadata = _normalize_json_value(
            metadata,
            "metadata",
            budget=_task_encoding_budget(
                task_id,
                name,
                prompt,
                timeout_seconds,
                task_priority,
            ),
        )
    except DeclaredAgentTaskError as exc:
        if str(exc) == f"Declared agent task exceeds {MAX_DECLARED_TASK_BYTES} bytes":
            raise
        raise DeclaredAgentTaskError(
            "Declared agent task metadata must be JSON-serializable"
        ) from exc

    payload = {
        "task_id": task_id,
        "agent_name": name,
        "prompt": prompt,
        "timeout": timeout_seconds,
        "priority": task_priority,
        "metadata": normalized_metadata,
    }
    return _encode_bounded_json(payload)


def _decode_task(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        raise RuntimeError("Declared agent worker task is invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RuntimeError("Declared agent worker task is invalid") from exc
    if len(encoded) > MAX_DECLARED_TASK_BYTES:
        raise RuntimeError("Declared agent worker task exceeds the input limit")
    try:
        payload = json.loads(
            value,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise RuntimeError("Declared agent worker task is invalid") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("Declared agent worker task is invalid")
    expected = {
        "task_id",
        "agent_name",
        "prompt",
        "timeout",
        "priority",
        "metadata",
    }
    if set(payload) != expected:
        raise RuntimeError("Declared agent worker task is invalid")
    try:
        task_id = payload["task_id"]
        if not isinstance(task_id, str) or not task_id:
            raise DeclaredAgentTaskError("task_id must be a non-empty string")
        _validate_utf8_string(task_id, "task_id")
        agent_name = _validate_identifier(payload["agent_name"], "agent_name")
        prompt = payload["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise DeclaredAgentTaskError("prompt must be a non-empty string")
        _validate_utf8_string(prompt, "prompt")
        timeout = _validate_timeout(payload["timeout"])
        priority = _validate_priority(payload["priority"])
        metadata = payload["metadata"]
        if not isinstance(metadata, Mapping):
            raise DeclaredAgentTaskError("metadata must be an object")
        normalized_metadata = _normalize_json_value(metadata, "metadata")
    except DeclaredAgentTaskError as exc:
        raise RuntimeError("Declared agent worker task is invalid") from exc
    return {
        "task_id": task_id,
        "agent_name": agent_name,
        "prompt": prompt,
        "timeout": timeout,
        "priority": priority,
        "metadata": normalized_metadata,
    }


def _echo_runner(task: Mapping[str, Any]) -> dict[str, Any]:
    metadata = task["metadata"]
    delay_ms = metadata.get("delay_ms", 0)
    if (
        not isinstance(delay_ms, int)
        or isinstance(delay_ms, bool)
        or not 0 <= delay_ms <= MAX_DECLARED_DELAY_MILLISECONDS
    ):
        raise RuntimeError(
            "Declared echo runner delay_ms must be an integer within the limit"
        )
    if delay_ms:
        time.sleep(delay_ms / 1000)
    return {
        "agent_name": task["agent_name"],
        "metadata": dict(metadata),
        "priority": task["priority"],
        "prompt": task["prompt"],
        "task_id": task["task_id"],
        "timeout": task["timeout"],
        "worker_pid": os.getpid(),
    }


_DECLARED_RUNNERS = {"echo": _echo_runner}


def is_known_runner(runner_id: object) -> bool:
    return type(runner_id) is str and runner_id in _DECLARED_RUNNERS


def _validate_importable_callable(handler: object) -> tuple[str, str]:
    """Return a stable locator for a module-level function, or reject it."""
    if type(handler) is not types.FunctionType:
        raise ValueError(
            "Worker handler must be a top-level importable function"
        )
    module_name = handler.__module__
    function_name = handler.__qualname__
    if (
        type(module_name) is not str
        or not module_name
        or module_name == "__main__"
        or type(function_name) is not str
        or not function_name.isidentifier()
    ):
        raise ValueError(
            "Worker handler must be a top-level importable function"
        )
    module = sys.modules.get(module_name)
    if module is None or module.__dict__.get(function_name) is not handler:
        raise ValueError(
            "Worker handler must be a top-level importable function"
        )
    return module_name, function_name


def _resolve_importable_callable(
    module_name: object,
    function_name: object,
) -> types.FunctionType:
    if (
        type(module_name) is not str
        or not module_name
        or module_name == "__main__"
        or type(function_name) is not str
        or not function_name.isidentifier()
    ):
        raise RuntimeError("Importable worker function is unavailable")
    try:
        module = importlib.import_module(module_name)
    except (ImportError, ValueError) as exc:
        raise RuntimeError("Importable worker function is unavailable") from exc
    handler = module.__dict__.get(function_name)
    if type(handler) is not types.FunctionType:
        raise RuntimeError("Importable worker function is unavailable")
    return handler


def execute_declared_agent_task(
    request_value: Mapping[str, Any],
    trusted_config: Mapping[str, Any],
) -> object:
    """Child-process entry point that resolves one static declared runner."""
    request = WorkerTaskRequest.from_dict(request_value)
    if not isinstance(trusted_config, Mapping) or set(trusted_config) != {"runner_id"}:
        raise RuntimeError("Declared agent worker configuration is invalid")
    runner_id = trusted_config["runner_id"]
    if not is_known_runner(runner_id):
        raise RuntimeError("Declared agent worker runner is unavailable")
    task = _decode_task(request.prompt)
    if task["agent_name"] != request.role_name or task["timeout"] != request.timeout_seconds:
        raise RuntimeError("Declared agent worker task does not match its request")
    return _DECLARED_RUNNERS[runner_id](task)


def execute_importable_agent_task(
    request_value: Mapping[str, Any],
    trusted_config: Mapping[str, Any],
) -> object:
    """Invoke a validated module-level function in the child process."""
    request = WorkerTaskRequest.from_dict(request_value)
    if (
        not isinstance(trusted_config, Mapping)
        or set(trusted_config) != {"module_name", "function_name"}
    ):
        raise RuntimeError("Importable worker configuration is invalid")
    handler = _resolve_importable_callable(
        trusted_config["module_name"],
        trusted_config["function_name"],
    )
    task = _decode_task(request.prompt)
    if (
        task["agent_name"] != request.role_name
        or task["timeout"] != request.timeout_seconds
    ):
        raise RuntimeError("Importable worker task does not match its request")
    from core.brain.orchestrator import AgentResult, AgentTask

    output = handler(AgentTask(**task))
    if isinstance(output, AgentResult):
        return {"kind": "agent_result", "value": output.to_dict()}
    return {"kind": "value", "value": output}


class DeclaredAgentWorker:
    """Owns the existing Worker supervisor for one static generic Agent."""

    def __init__(self, name: str, runner_id: str) -> None:
        self.name = _validate_identifier(name, "agent_name")
        if not is_known_runner(runner_id):
            raise ValueError("Unknown declared runner")
        self.runner_id = runner_id
        self._supervisor = RoleWorkerSupervisor(
            execute_declared_agent_task,
            runner_config={"runner_id": runner_id},
        )
        self._active_task_id: str | None = None
        self._active_caller_task_id: str | None = None
        self._lock = threading.RLock()

    def dispatch(
        self,
        *,
        task_id: object,
        agent_name: object,
        prompt: object,
        timeout: object,
        priority: object,
        metadata: object,
    ) -> WorkerTaskRecord | None:
        validated_agent_name = _validate_identifier(agent_name, "agent_name")
        if validated_agent_name != self.name:
            raise DeclaredAgentTaskError("agent_name does not match its registration")
        encoded_task = _encode_task(
            task_id=task_id,
            agent_name=validated_agent_name,
            prompt=prompt,
            timeout=timeout,
            priority=priority,
            metadata=metadata,
        )
        request = WorkerTaskRequest.new(
            self.name,
            encoded_task,
            _validate_timeout(timeout),
            task_id=f"declared-{uuid.uuid4().hex}",
        )
        with self._lock:
            self._reap_confirmed_locked()
            if self._active_task_id is not None:
                raise RuntimeError("Declared agent worker is still active")
            self._active_task_id = request.task_id
            self._active_caller_task_id = task_id
            try:
                record = self._supervisor.submit(request)
            except BaseException:
                try:
                    submission_started = self._supervisor.get(request.task_id) is not None
                except Exception:
                    submission_started = True
                if not submission_started:
                    self._active_task_id = None
                    self._active_caller_task_id = None
                raise

        record = self._supervisor.wait(
            request.task_id,
            self._supervisor.terminal_wait_budget(request.timeout_seconds),
        )
        with self._lock:
            self._reap_confirmed_locked()
        return record

    def decode_result(self, value: object) -> object:
        """Decode a successful Worker result for the generic result mapper."""
        return value

    def cancel(self, caller_task_id: object) -> WorkerTaskRecord | None:
        """Request cancellation for the matching caller task."""
        if type(caller_task_id) is not str:
            return None
        with self._lock:
            self._reap_confirmed_locked()
            if self._active_caller_task_id != caller_task_id:
                return None
            worker_task_id = self._active_task_id
        if worker_task_id is None:
            return None
        try:
            record = self._supervisor.cancel(worker_task_id)
        except WorkerTaskTerminalError as exc:
            record = exc.record
        with self._lock:
            self._reap_confirmed_locked()
        return record

    def has_pending_execution(self) -> bool:
        with self._lock:
            self._reap_confirmed_locked()
            return self._active_task_id is not None

    def shutdown(self) -> None:
        self._supervisor.shutdown()
        with self._lock:
            self._reap_confirmed_locked()

    def _reap_confirmed_locked(self) -> None:
        if self._active_task_id is None:
            return
        record = self._supervisor.get(self._active_task_id)
        if (
            record is not None
            and record.status.is_terminal
            and record.termination_confirmed
        ):
            self._active_task_id = None
            self._active_caller_task_id = None


class ImportableAgentWorker(DeclaredAgentWorker):
    """Worker adapter for a stable module-level Python function."""

    def __init__(self, name: str, handler: object) -> None:
        self.name = _validate_identifier(name, "agent_name")
        module_name, function_name = _validate_importable_callable(handler)
        self.module_name = module_name
        self.function_name = function_name
        self.runner_id = f"{module_name}:{function_name}"
        self._supervisor = RoleWorkerSupervisor(
            execute_importable_agent_task,
            runner_config={
                "module_name": module_name,
                "function_name": function_name,
            },
        )
        self._active_task_id: str | None = None
        self._active_caller_task_id: str | None = None
        self._lock = threading.RLock()

    def decode_result(self, value: object) -> object:
        if not isinstance(value, Mapping) or set(value) != {"kind", "value"}:
            raise RuntimeError("Importable worker result envelope is invalid")
        kind = value["kind"]
        if kind == "value":
            return value["value"]
        if kind != "agent_result" or not isinstance(value["value"], Mapping):
            raise RuntimeError("Importable worker result envelope is invalid")
        raw = value["value"]
        expected = {
            "task_id",
            "agent_name",
            "result",
            "error",
            "duration_ms",
            "status",
        }
        if set(raw) != expected:
            raise RuntimeError("Importable worker AgentResult is invalid")
        from core.brain.orchestrator import AgentResult

        return AgentResult(**{field: raw[field] for field in expected})
