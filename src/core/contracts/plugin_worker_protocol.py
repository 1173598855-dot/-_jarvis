"""Strict, versioned JSON-lines messages for isolated plugin workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


PLUGIN_WORKER_PROTOCOL_VERSION = 1
MAX_PLUGIN_WORKER_LINE_BYTES = 65_536
_MAX_ERROR_CHARACTERS = 1_024
_MAX_AUDIT_ENTRIES = 100
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "credential", "authorization", "api_key")
_SENSITIVE_TEXT_VALUE = re.compile(
    r"(?i)\b(token|secret|password|credential|authorization|api[_-]?key)\b\s*([=:])\s*[^\s,;]+"
)

HELLO_FIELDS = frozenset({"protocol_version", "kind", "worker_id", "pid"})
LIFECYCLE_REQUEST_FIELDS = frozenset(
    {"protocol_version", "kind", "request_id", "plugin_id", "action", "payload"}
)
BROKER_REQUEST_FIELDS = frozenset(
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
BROKER_RESULT_FIELDS = frozenset(
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
LIFECYCLE_RESULT_FIELDS = frozenset(
    {"protocol_version", "kind", "request_id", "plugin_id", "success", "status", "error", "audit"}
)
_LOAD_SPEC_FIELDS = frozenset({"entry_point", "permissions", "api_version", "generation"})
_LIFECYCLE_STATUSES = frozenset({"loaded", "enabled", "disabled", "error", "unloaded"})


class PluginWorkerProtocolError(ValueError):
    """Raised when plugin worker input violates the protocol contract."""


class LifecycleAction(str, Enum):
    LOAD = "load"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    CLEANUP = "cleanup"
    SHUTDOWN = "shutdown"


def _require_version(value: object) -> int:
    if type(value) is not int or value != PLUGIN_WORKER_PROTOCOL_VERSION:
        raise PluginWorkerProtocolError(
            f"protocol_version must be {PLUGIN_WORKER_PROTOCOL_VERSION}"
        )
    return value


def _require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PluginWorkerProtocolError(
            f"{field_name} must be a canonical non-empty identifier"
        )
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PluginWorkerProtocolError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise PluginWorkerProtocolError(f"{field_name} must be a positive integer")
    return value


def _require_json(value: Any, path: str = "value") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if type(value) is int:
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise PluginWorkerProtocolError(f"{path} must not contain non-finite numbers")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PluginWorkerProtocolError(f"{path} object keys must be strings")
            _require_json(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _require_json(item, f"{path}[{index}]")
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


def stable_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 bytes for a JSON-compatible value."""
    _require_json(value)
    return json.dumps(
        _thaw(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_mapping(value: object, expected: frozenset[str], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PluginWorkerProtocolError(f"{field_name} must be an object")
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unknown:
            details.append(f"unknown {sorted(unknown)}")
        raise PluginWorkerProtocolError(f"{field_name} has {'; '.join(details)} fields")
    return value


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def redact_protocol_error(value: Any) -> str:
    """Render errors without line breaks, sensitive mapping values, or excess text."""
    redacted = _redact_value(value)
    if isinstance(redacted, str):
        text = redacted
    else:
        try:
            text = stable_json_bytes(redacted).decode("utf-8")
        except PluginWorkerProtocolError:
            text = type(value).__name__
    text = _SENSITIVE_TEXT_VALUE.sub(r"\1\2<redacted>", text)
    text = text.replace("\r", " ").replace("\n", " ")
    return text[:_MAX_ERROR_CHARACTERS]


def _require_error(value: object, field_name: str = "error") -> str:
    if not isinstance(value, str):
        raise PluginWorkerProtocolError(f"{field_name} must be a string")
    return redact_protocol_error(value)


@dataclass(frozen=True, slots=True)
class PluginLoadSpec:
    entry_point: str
    permissions: tuple[str, ...]
    api_version: str
    generation: int

    def __post_init__(self) -> None:
        _require_text(self.entry_point, "entry_point")
        if not isinstance(self.permissions, (list, tuple)):
            raise PluginWorkerProtocolError("permissions must be a list of strings")
        permissions = tuple(_require_text(permission, "permission") for permission in self.permissions)
        _require_text(self.api_version, "api_version")
        _require_positive_int(self.generation, "generation")
        object.__setattr__(self, "permissions", permissions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_point": self.entry_point,
            "permissions": list(self.permissions),
            "api_version": self.api_version,
            "generation": self.generation,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PluginLoadSpec":
        raw = _strict_mapping(value, _LOAD_SPEC_FIELDS, "plugin load spec")
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
    protocol_version: int = field(default=PLUGIN_WORKER_PROTOCOL_VERSION, kw_only=True)

    def __post_init__(self) -> None:
        _require_version(self.protocol_version)
        _require_identifier(self.worker_id, "worker_id")
        _require_positive_int(self.pid, "pid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "kind": "hello",
            "worker_id": self.worker_id,
            "pid": self.pid,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PluginWorkerHello":
        raw = _strict_mapping(value, HELLO_FIELDS, "plugin worker hello")
        if raw["kind"] != "hello":
            raise PluginWorkerProtocolError("plugin worker hello kind must be hello")
        return cls(worker_id=raw["worker_id"], pid=raw["pid"], protocol_version=raw["protocol_version"])


@dataclass(frozen=True, slots=True)
class PluginLifecycleRequest:
    request_id: str
    plugin_id: str
    action: LifecycleAction
    payload: Mapping[str, Any]
    protocol_version: int = field(default=PLUGIN_WORKER_PROTOCOL_VERSION, kw_only=True)

    def __post_init__(self) -> None:
        _require_version(self.protocol_version)
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.plugin_id, "plugin_id")
        if not isinstance(self.action, LifecycleAction):
            raise PluginWorkerProtocolError("action must be a supported LifecycleAction")
        if not isinstance(self.payload, Mapping):
            raise PluginWorkerProtocolError("payload must be an object")
        if self.action is LifecycleAction.LOAD:
            payload = PluginLoadSpec.from_dict(self.payload).to_dict()
        elif self.payload:
            raise PluginWorkerProtocolError("non-load lifecycle payload must be empty")
        else:
            payload = {}
        object.__setattr__(self, "payload", _freeze(payload))

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
    def from_dict(cls, value: object) -> "PluginLifecycleRequest":
        raw = _strict_mapping(value, LIFECYCLE_REQUEST_FIELDS, "plugin lifecycle request")
        if raw["kind"] != "lifecycle_request":
            raise PluginWorkerProtocolError("plugin lifecycle request kind is invalid")
        try:
            action = LifecycleAction(raw["action"])
        except (TypeError, ValueError) as exc:
            raise PluginWorkerProtocolError("lifecycle action is unsupported") from exc
        return cls(
            request_id=raw["request_id"],
            plugin_id=raw["plugin_id"],
            action=action,
            payload=raw["payload"],
            protocol_version=raw["protocol_version"],
        )


@dataclass(frozen=True, slots=True)
class PluginBrokerRequest:
    request_id: str
    call_id: str
    plugin_id: str
    capability: str
    arguments: Mapping[str, Any]
    protocol_version: int = field(default=PLUGIN_WORKER_PROTOCOL_VERSION, kw_only=True)

    def __post_init__(self) -> None:
        _require_version(self.protocol_version)
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.call_id, "call_id")
        _require_identifier(self.plugin_id, "plugin_id")
        _require_identifier(self.capability, "capability")
        if not isinstance(self.arguments, Mapping):
            raise PluginWorkerProtocolError("arguments must be an object")
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
    def from_dict(cls, value: object) -> "PluginBrokerRequest":
        raw = _strict_mapping(value, BROKER_REQUEST_FIELDS, "plugin broker request")
        if raw["kind"] != "broker_request":
            raise PluginWorkerProtocolError("plugin broker request kind is invalid")
        return cls(
            request_id=raw["request_id"],
            call_id=raw["call_id"],
            plugin_id=raw["plugin_id"],
            capability=raw["capability"],
            arguments=raw["arguments"],
            protocol_version=raw["protocol_version"],
        )


@dataclass(frozen=True, slots=True)
class PluginBrokerResult:
    request_id: str
    call_id: str
    plugin_id: str
    allowed: bool
    result: Any
    error: str
    protocol_version: int = field(default=PLUGIN_WORKER_PROTOCOL_VERSION, kw_only=True)

    def __post_init__(self) -> None:
        _require_version(self.protocol_version)
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.call_id, "call_id")
        _require_identifier(self.plugin_id, "plugin_id")
        if not isinstance(self.allowed, bool):
            raise PluginWorkerProtocolError("allowed must be a boolean")
        _require_json(self.result, "result")
        error = _require_error(self.error)
        if self.allowed and error:
            raise PluginWorkerProtocolError("allowed broker results must have an empty error")
        if not self.allowed:
            _require_identifier(error, "denial error")
        object.__setattr__(self, "result", _freeze(self.result))
        object.__setattr__(self, "error", error)

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
    def from_dict(cls, value: object) -> "PluginBrokerResult":
        raw = _strict_mapping(value, BROKER_RESULT_FIELDS, "plugin broker result")
        if raw["kind"] != "broker_result":
            raise PluginWorkerProtocolError("plugin broker result kind is invalid")
        return cls(
            request_id=raw["request_id"],
            call_id=raw["call_id"],
            plugin_id=raw["plugin_id"],
            allowed=raw["allowed"],
            result=raw["result"],
            error=raw["error"],
            protocol_version=raw["protocol_version"],
        )


@dataclass(frozen=True, slots=True)
class PluginLifecycleResult:
    request_id: str
    plugin_id: str
    success: bool
    status: str
    error: str
    audit: tuple[Any, ...]
    protocol_version: int = field(default=PLUGIN_WORKER_PROTOCOL_VERSION, kw_only=True)

    def __post_init__(self) -> None:
        _require_version(self.protocol_version)
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.plugin_id, "plugin_id")
        if not isinstance(self.success, bool):
            raise PluginWorkerProtocolError("success must be a boolean")
        if self.status not in _LIFECYCLE_STATUSES:
            raise PluginWorkerProtocolError("lifecycle result status is unsupported")
        error = _require_error(self.error)
        if not isinstance(self.audit, (list, tuple)):
            raise PluginWorkerProtocolError("audit must be a JSON-compatible array")
        if len(self.audit) > _MAX_AUDIT_ENTRIES:
            raise PluginWorkerProtocolError("audit cannot contain more than 100 entries")
        _require_json(self.audit, "audit")
        object.__setattr__(self, "error", error)
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
    def from_dict(cls, value: object) -> "PluginLifecycleResult":
        raw = _strict_mapping(value, LIFECYCLE_RESULT_FIELDS, "plugin lifecycle result")
        if raw["kind"] != "lifecycle_result":
            raise PluginWorkerProtocolError("plugin lifecycle result kind is invalid")
        return cls(
            request_id=raw["request_id"],
            plugin_id=raw["plugin_id"],
            success=raw["success"],
            status=raw["status"],
            error=raw["error"],
            audit=raw["audit"],
            protocol_version=raw["protocol_version"],
        )


ProtocolMessage: TypeAlias = (
    PluginWorkerHello
    | PluginLifecycleRequest
    | PluginBrokerRequest
    | PluginBrokerResult
    | PluginLifecycleResult
)

_MESSAGE_TYPES: dict[str, type[ProtocolMessage]] = {
    "hello": PluginWorkerHello,
    "lifecycle_request": PluginLifecycleRequest,
    "broker_request": PluginBrokerRequest,
    "broker_result": PluginBrokerResult,
    "lifecycle_result": PluginLifecycleResult,
}


def encode_message(message: ProtocolMessage) -> bytes:
    """Encode one validated protocol record as a bounded JSON line."""
    if not isinstance(message, tuple(_MESSAGE_TYPES.values())):
        raise PluginWorkerProtocolError("message must be a plugin worker protocol record")
    line = stable_json_bytes(message.to_dict())
    if len(line) + 1 > MAX_PLUGIN_WORKER_LINE_BYTES:
        raise PluginWorkerProtocolError("encoded protocol line exceeds maximum byte length")
    return line + b"\n"


def _reject_json_constant(value: str) -> None:
    raise PluginWorkerProtocolError(f"unsupported JSON constant {value}")


def decode_message(line: bytes) -> ProtocolMessage:
    """Decode exactly one bounded, validated plugin worker JSON message."""
    if not isinstance(line, bytes):
        raise PluginWorkerProtocolError("protocol line must be bytes")
    if not line or len(line) > MAX_PLUGIN_WORKER_LINE_BYTES:
        raise PluginWorkerProtocolError("protocol line has an invalid byte length")
    if line.endswith(b"\n"):
        line = line[:-1]
    if not line or b"\n" in line or b"\r" in line:
        raise PluginWorkerProtocolError("protocol line must contain one JSON value")
    try:
        decoded = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PluginWorkerProtocolError("protocol line must be valid UTF-8") from exc
    try:
        raw = json.loads(decoded, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PluginWorkerProtocolError("protocol line must contain valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise PluginWorkerProtocolError("protocol message must be an object")
    kind = raw.get("kind")
    message_type = _MESSAGE_TYPES.get(kind)
    if message_type is None:
        raise PluginWorkerProtocolError("protocol message kind is unsupported")
    return message_type.from_dict(raw)
