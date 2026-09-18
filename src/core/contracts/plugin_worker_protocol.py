"""Strict, newline-delimited values for the plugin worker boundary."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

PLUGIN_WORKER_PROTOCOL_VERSION = 1
MAX_PLUGIN_WORKER_LINE_BYTES = 65_536
# Keep recursive normalization below Python's call-stack limit for untrusted JSON.
MAX_PLUGIN_WORKER_JSON_DEPTH = 256
# Stay below CPython's minimum configurable nonzero integer-string limit.
MAX_PLUGIN_WORKER_INTEGER_DIGITS = 512
_MAX_PLUGIN_WORKER_INTEGER_MAGNITUDE = 10 ** MAX_PLUGIN_WORKER_INTEGER_DIGITS
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ERROR_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_ -]?key|authorization|password|secret|token)\s*[:=]\s*[^\s,;]+"
)
_ERROR_BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_LIFECYCLE_STATUSES = frozenset({"loaded", "enabled", "disabled", "error", "unloaded"})


class PluginWorkerProtocolError(ValueError):
    """Raised when a plugin worker protocol value is malformed."""


def _require_bounded_integer(value: int, path: str) -> None:
    if (
        value >= _MAX_PLUGIN_WORKER_INTEGER_MAGNITUDE
        or value <= -_MAX_PLUGIN_WORKER_INTEGER_MAGNITUDE
    ):
        raise PluginWorkerProtocolError(f"{path} exceeds integer digit limit")


class LifecycleAction(str, Enum):
    LOAD = "load"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    CLEANUP = "cleanup"
    SHUTDOWN = "shutdown"


def _require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise PluginWorkerProtocolError(
            f"{field_name} must be a canonical non-empty identifier"
        )
    _require_utf8_string(value, field_name)
    if not _IDENTIFIER.fullmatch(value):
        raise PluginWorkerProtocolError(
            f"{field_name} must be a canonical non-empty identifier"
        )
    return value


def _require_positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise PluginWorkerProtocolError(f"{field_name} must be a positive integer")
    _require_bounded_integer(value, field_name)
    return value


def _require_utf8_string(value: str, path: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise PluginWorkerProtocolError(
            f"{path} must not contain invalid Unicode"
        ) from error
    return value


def _require_json(value: Any, path: str = "value", *, depth: int = 0) -> None:
    if depth > MAX_PLUGIN_WORKER_JSON_DEPTH:
        raise PluginWorkerProtocolError(f"{path} exceeds JSON nesting depth")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        _require_utf8_string(value, path)
        return
    if type(value) is int:
        _require_bounded_integer(value, path)
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise PluginWorkerProtocolError(f"{path} must not contain non-finite numbers")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PluginWorkerProtocolError(f"{path} object keys must be strings")
            _require_utf8_string(key, f"{path} object key")
            _require_json(item, f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _require_json(item, f"{path}[{index}]", depth=depth + 1)
        return
    raise PluginWorkerProtocolError(f"{path} contains an unsupported JSON value")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _strict_mapping(value: object, expected: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PluginWorkerProtocolError(f"{name} must be an object")
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unknown:
            details.append(f"unknown {sorted(unknown, key=repr)}")
        raise PluginWorkerProtocolError(f"{name} has {'; '.join(details)}")
    return value


def _require_version(value: object) -> None:
    if type(value) is not int or value != PLUGIN_WORKER_PROTOCOL_VERSION:
        raise PluginWorkerProtocolError(
            f"protocol_version must be {PLUGIN_WORKER_PROTOCOL_VERSION}"
        )


def stable_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible data with deterministic UTF-8 representation."""
    _require_json(value)
    try:
        return json.dumps(
            _thaw(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except UnicodeEncodeError as error:
        raise PluginWorkerProtocolError("value must not contain invalid Unicode") from error


def bounded_stable_json_size(value: Any, max_bytes: int) -> int:
    """Return canonical JSON size without materializing values beyond a byte cap."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")

    total = 0

    def add(size: int) -> None:
        nonlocal total
        total += size
        if total > max_bytes:
            raise OverflowError("value exceeds JSON byte limit")

    def add_string(item: str, path: str) -> None:
        add(2)
        for character in item:
            codepoint = ord(character)
            if codepoint in {0x22, 0x5C, 0x08, 0x09, 0x0A, 0x0C, 0x0D}:
                add(2)
            elif codepoint < 0x20:
                add(6)
            elif codepoint < 0x80:
                add(1)
            elif codepoint < 0x800:
                add(2)
            elif 0xD800 <= codepoint <= 0xDFFF:
                raise PluginWorkerProtocolError(
                    f"{path} must not contain invalid Unicode"
                )
            elif codepoint < 0x10000:
                add(3)
            else:
                add(4)

    def visit(item: Any, path: str, depth: int) -> None:
        if depth > MAX_PLUGIN_WORKER_JSON_DEPTH:
            raise PluginWorkerProtocolError(f"{path} exceeds JSON nesting depth")
        if item is None:
            add(4)
        elif isinstance(item, bool):
            add(4 if item else 5)
        elif isinstance(item, str):
            add_string(item, path)
        elif type(item) is int:
            _require_bounded_integer(item, path)
            add(len(str(item)))
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise PluginWorkerProtocolError(
                    f"{path} must not contain non-finite numbers"
                )
            add(len(json.dumps(item, allow_nan=False).encode("utf-8")))
        elif isinstance(item, Mapping):
            add(1)
            for index, (key, nested) in enumerate(item.items()):
                if not isinstance(key, str):
                    raise PluginWorkerProtocolError(
                        f"{path} object keys must be strings"
                    )
                if index:
                    add(1)
                add_string(key, f"{path} object key")
                add(1)
                visit(nested, f"{path}.{key}", depth + 1)
            add(1)
        elif isinstance(item, (list, tuple)):
            add(1)
            for index, nested in enumerate(item):
                if index:
                    add(1)
                visit(nested, f"{path}[{index}]", depth + 1)
            add(1)
        else:
            raise PluginWorkerProtocolError(
                f"{path} contains an unsupported JSON value"
            )

    visit(value, "value", 0)
    return total


def redact_protocol_error(value: object) -> str:
    """Produce bounded single-line diagnostics that do not retain common secrets."""
    if not isinstance(value, str):
        return "protocol_error"
    _require_utf8_string(value, "error")
    redacted = value.replace("\r", " ").replace("\n", " ")
    redacted = _ERROR_ASSIGNMENT.sub("[REDACTED]", redacted)
    redacted = _ERROR_BEARER.sub("Bearer [REDACTED]", redacted)
    return redacted[:1024]


@dataclass(frozen=True, slots=True)
class PluginLoadSpec:
    entry_point: str
    permissions: tuple[str, ...]
    api_version: str
    generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.entry_point, str):
            raise PluginWorkerProtocolError("entry_point must be a string")
        _require_utf8_string(self.entry_point, "entry_point")
        if not isinstance(self.permissions, (list, tuple)) or any(
            not isinstance(permission, str) for permission in self.permissions
        ):
            raise PluginWorkerProtocolError("permissions must be an array of strings")
        for permission in self.permissions:
            _require_utf8_string(permission, "permissions")
        if not isinstance(self.api_version, str):
            raise PluginWorkerProtocolError("api_version must be a string")
        _require_utf8_string(self.api_version, "api_version")
        _require_positive_integer(self.generation, "generation")
        object.__setattr__(self, "permissions", tuple(self.permissions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_point": self.entry_point,
            "permissions": list(self.permissions),
            "api_version": self.api_version,
            "generation": self.generation,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginLoadSpec:
        fields = frozenset({"entry_point", "permissions", "api_version", "generation"})
        raw = _strict_mapping(value, fields, "load payload")
        return cls(
            entry_point=raw["entry_point"],
            permissions=raw["permissions"],
            api_version=raw["api_version"],
            generation=raw["generation"],
        )


@dataclass(frozen=True, slots=True)
class PluginWorkerHello:
    worker_id: str
    pid: int
    protocol_version: int = field(
        default=PLUGIN_WORKER_PROTOCOL_VERSION, init=False, repr=False
    )

    def __post_init__(self) -> None:
        _require_identifier(self.worker_id, "worker_id")
        _require_positive_integer(self.pid, "pid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "kind": "hello",
            "worker_id": self.worker_id,
            "pid": self.pid,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginWorkerHello:
        fields = frozenset({"protocol_version", "kind", "worker_id", "pid"})
        raw = _strict_mapping(value, fields, "hello")
        _require_version(raw["protocol_version"])
        if raw["kind"] != "hello":
            raise PluginWorkerProtocolError("hello kind must be hello")
        return cls(worker_id=raw["worker_id"], pid=raw["pid"])


@dataclass(frozen=True, slots=True)
class PluginLifecycleRequest:
    request_id: str
    plugin_id: str
    action: LifecycleAction
    payload: Mapping[str, Any]
    protocol_version: int = field(
        default=PLUGIN_WORKER_PROTOCOL_VERSION, init=False, repr=False
    )

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.plugin_id, "plugin_id")
        if not isinstance(self.action, LifecycleAction):
            raise PluginWorkerProtocolError("action must be a supported LifecycleAction")
        if not isinstance(self.payload, Mapping):
            raise PluginWorkerProtocolError("payload must be an object")
        if self.action is LifecycleAction.LOAD:
            normalized_payload = PluginLoadSpec.from_dict(self.payload).to_dict()
        elif self.payload:
            raise PluginWorkerProtocolError("non-load lifecycle payloads must be empty")
        else:
            normalized_payload = {}
        object.__setattr__(self, "payload", _freeze(normalized_payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "kind": "lifecycle_request",
            "request_id": self.request_id,
            "plugin_id": self.plugin_id,
            "action": self.action.value,
            "payload": _thaw(self.payload),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginLifecycleRequest:
        fields = frozenset(
            {"protocol_version", "kind", "request_id", "plugin_id", "action", "payload"}
        )
        raw = _strict_mapping(value, fields, "lifecycle request")
        _require_version(raw["protocol_version"])
        if raw["kind"] != "lifecycle_request":
            raise PluginWorkerProtocolError("lifecycle request kind is invalid")
        try:
            action = LifecycleAction(raw["action"])
        except (TypeError, ValueError) as error:
            raise PluginWorkerProtocolError("lifecycle action is unsupported") from error
        return cls(
            request_id=raw["request_id"],
            plugin_id=raw["plugin_id"],
            action=action,
            payload=raw["payload"],
        )


@dataclass(frozen=True, slots=True)
class PluginBrokerRequest:
    request_id: str
    call_id: str
    plugin_id: str
    capability: str
    arguments: Any
    protocol_version: int = field(
        default=PLUGIN_WORKER_PROTOCOL_VERSION, init=False, repr=False
    )

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.call_id, "call_id")
        _require_identifier(self.plugin_id, "plugin_id")
        _require_identifier(self.capability, "capability")
        _require_json(self.arguments, "arguments")
        object.__setattr__(self, "arguments", _freeze(self.arguments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "kind": "broker_request",
            "request_id": self.request_id,
            "call_id": self.call_id,
            "plugin_id": self.plugin_id,
            "capability": self.capability,
            "arguments": _thaw(self.arguments),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginBrokerRequest:
        fields = frozenset(
            {
                "protocol_version",
                "kind",
                "request_id",
                "call_id",
                "plugin_id",
                "capability",
                "arguments",
            }
        )
        raw = _strict_mapping(value, fields, "broker request")
        _require_version(raw["protocol_version"])
        if raw["kind"] != "broker_request":
            raise PluginWorkerProtocolError("broker request kind is invalid")
        return cls(
            request_id=raw["request_id"],
            call_id=raw["call_id"],
            plugin_id=raw["plugin_id"],
            capability=raw["capability"],
            arguments=raw["arguments"],
        )


@dataclass(frozen=True, slots=True)
class PluginBrokerResult:
    request_id: str
    call_id: str
    plugin_id: str
    allowed: bool
    result: Any
    error: str
    protocol_version: int = field(
        default=PLUGIN_WORKER_PROTOCOL_VERSION, init=False, repr=False
    )

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.call_id, "call_id")
        _require_identifier(self.plugin_id, "plugin_id")
        if type(self.allowed) is not bool:
            raise PluginWorkerProtocolError("allowed must be a boolean")
        _require_json(self.result, "result")
        if not isinstance(self.error, str):
            raise PluginWorkerProtocolError("error must be a string")
        if self.allowed and self.error:
            raise PluginWorkerProtocolError("allowed broker results must have an empty error")
        if not self.allowed and not _ERROR_CODE.fullmatch(self.error):
            raise PluginWorkerProtocolError("denied broker results require a stable error code")
        object.__setattr__(self, "result", _freeze(self.result))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "kind": "broker_result",
            "request_id": self.request_id,
            "call_id": self.call_id,
            "plugin_id": self.plugin_id,
            "allowed": self.allowed,
            "result": _thaw(self.result),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginBrokerResult:
        fields = frozenset(
            {
                "protocol_version",
                "kind",
                "request_id",
                "call_id",
                "plugin_id",
                "allowed",
                "result",
                "error",
            }
        )
        raw = _strict_mapping(value, fields, "broker result")
        _require_version(raw["protocol_version"])
        if raw["kind"] != "broker_result":
            raise PluginWorkerProtocolError("broker result kind is invalid")
        return cls(
            request_id=raw["request_id"],
            call_id=raw["call_id"],
            plugin_id=raw["plugin_id"],
            allowed=raw["allowed"],
            result=raw["result"],
            error=raw["error"],
        )


@dataclass(frozen=True, slots=True)
class PluginLifecycleResult:
    request_id: str
    plugin_id: str
    success: bool
    status: str
    error: str
    audit: tuple[Any, ...]
    protocol_version: int = field(
        default=PLUGIN_WORKER_PROTOCOL_VERSION, init=False, repr=False
    )

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.plugin_id, "plugin_id")
        if type(self.success) is not bool:
            raise PluginWorkerProtocolError("success must be a boolean")
        if not isinstance(self.status, str):
            raise PluginWorkerProtocolError("lifecycle result status is unsupported")
        _require_utf8_string(self.status, "status")
        if self.status not in _LIFECYCLE_STATUSES:
            raise PluginWorkerProtocolError("lifecycle result status is unsupported")
        if not isinstance(self.error, str):
            raise PluginWorkerProtocolError("error must be a string")
        _require_utf8_string(self.error, "error")
        if not isinstance(self.audit, (list, tuple)) or len(self.audit) > 100:
            raise PluginWorkerProtocolError("audit must be an array with at most 100 entries")
        _require_json(self.audit, "audit")
        object.__setattr__(self, "error", redact_protocol_error(self.error))
        object.__setattr__(self, "audit", tuple(_freeze(item) for item in self.audit))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "kind": "lifecycle_result",
            "request_id": self.request_id,
            "plugin_id": self.plugin_id,
            "success": self.success,
            "status": self.status,
            "error": self.error,
            "audit": _thaw(self.audit),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginLifecycleResult:
        fields = frozenset(
            {
                "protocol_version",
                "kind",
                "request_id",
                "plugin_id",
                "success",
                "status",
                "error",
                "audit",
            }
        )
        raw = _strict_mapping(value, fields, "lifecycle result")
        _require_version(raw["protocol_version"])
        if raw["kind"] != "lifecycle_result":
            raise PluginWorkerProtocolError("lifecycle result kind is invalid")
        return cls(
            request_id=raw["request_id"],
            plugin_id=raw["plugin_id"],
            success=raw["success"],
            status=raw["status"],
            error=raw["error"],
            audit=raw["audit"],
        )


ProtocolMessage: TypeAlias = (
    PluginWorkerHello
    | PluginLifecycleRequest
    | PluginBrokerRequest
    | PluginBrokerResult
    | PluginLifecycleResult
)


def encode_message(message: ProtocolMessage) -> bytes:
    """Encode one validated message as a bounded canonical JSON line."""
    if not isinstance(
        message,
        (
            PluginWorkerHello,
            PluginLifecycleRequest,
            PluginBrokerRequest,
            PluginBrokerResult,
            PluginLifecycleResult,
        ),
    ):
        raise PluginWorkerProtocolError("message must be a validated protocol record")
    line = stable_json_bytes(message.to_dict()) + b"\n"
    if len(line) > MAX_PLUGIN_WORKER_LINE_BYTES:
        raise PluginWorkerProtocolError("protocol message exceeds line byte limit")
    return line


def decode_message(line: bytes) -> ProtocolMessage:
    """Decode and validate exactly one bounded canonical JSON message line."""
    if not isinstance(line, bytes):
        raise PluginWorkerProtocolError("protocol line must be bytes")
    if not line.endswith(b"\n") or b"\n" in line[:-1] or b"\r" in line:
        raise PluginWorkerProtocolError("protocol line must contain exactly one trailing newline")
    if len(line) > MAX_PLUGIN_WORKER_LINE_BYTES:
        raise PluginWorkerProtocolError("protocol message exceeds line byte limit")
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise PluginWorkerProtocolError("protocol message contains duplicate object keys")
            value[key] = item
        return value

    try:
        value = json.loads(
            line[:-1].decode("utf-8"),
            object_pairs_hook=unique_object,
        )
    except PluginWorkerProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise PluginWorkerProtocolError("protocol line must contain valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise PluginWorkerProtocolError("protocol message must be an object")
    kind = value.get("kind")
    decoders = {
        "hello": PluginWorkerHello,
        "lifecycle_request": PluginLifecycleRequest,
        "broker_request": PluginBrokerRequest,
        "broker_result": PluginBrokerResult,
        "lifecycle_result": PluginLifecycleResult,
    }
    decoder = decoders.get(kind)
    if decoder is None:
        raise PluginWorkerProtocolError("protocol message kind is unsupported")
    message = decoder.from_dict(value)
    if encode_message(message) != line:
        raise PluginWorkerProtocolError("protocol line must use canonical JSON encoding")
    return message
