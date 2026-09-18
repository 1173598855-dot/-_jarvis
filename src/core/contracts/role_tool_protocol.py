"""Immutable, versioned values used at the role-tool broker boundary."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional


class RoleToolProtocolError(ValueError):
    """Raised when an untrusted tool protocol value is malformed."""


_JSON_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)


def _require_json(value: Any, path: str = "value") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise RoleToolProtocolError(f"{path} must not contain non-finite numbers")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RoleToolProtocolError(f"{path} object keys must be strings")
            _require_json(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _require_json(item, f"{path}[{index}]")
        return
    raise RoleToolProtocolError(f"{path} contains an unsupported JSON value")


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
    """Serialize supported JSON values with deterministic UTF-8 sizing."""
    _require_json(value)
    return json.dumps(
        _thaw(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def bounded_stable_json_size(value: Any, max_bytes: int) -> int:
    """Return canonical JSON size without materializing values beyond a cap."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")

    total = 0

    def add(size: int) -> None:
        nonlocal total
        total += size
        if total > max_bytes:
            raise OverflowError("value exceeds JSON byte limit")

    def add_string(item: str) -> None:
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
                item.encode("utf-8")
            elif codepoint < 0x10000:
                add(3)
            else:
                add(4)

    def visit(item: Any, path: str) -> None:
        if item is None:
            add(4)
        elif isinstance(item, bool):
            add(4 if item else 5)
        elif isinstance(item, str):
            add_string(item)
        elif isinstance(item, int) and not isinstance(item, bool):
            add(len(str(item)))
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise RoleToolProtocolError(
                    f"{path} must not contain non-finite numbers"
                )
            add(len(json.dumps(item, allow_nan=False).encode("utf-8")))
        elif isinstance(item, Mapping):
            add(1)
            for index, (key, nested) in enumerate(item.items()):
                if not isinstance(key, str):
                    raise RoleToolProtocolError(
                        f"{path} object keys must be strings"
                    )
                if index:
                    add(1)
                add_string(key)
                add(1)
                visit(nested, f"{path}.{key}")
            add(1)
        elif isinstance(item, (list, tuple)):
            add(1)
            for index, nested in enumerate(item):
                if index:
                    add(1)
                visit(nested, f"{path}[{index}]")
            add(1)
        else:
            raise RoleToolProtocolError(
                f"{path} contains an unsupported JSON value"
            )

    visit(value, "value")
    return total


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, Mapping)
    if type_name == "array":
        return isinstance(value, (list, tuple))
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
    if type_name == "boolean":
        return isinstance(value, bool)
    return value is None


def _normalize_schema(schema: Any, *, root: bool = False) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        raise RoleToolProtocolError("Tool parameter schema must be an object")
    type_name = schema.get("type")
    if not isinstance(type_name, str) or type_name not in _JSON_TYPES:
        raise RoleToolProtocolError("Tool parameter schema has an unsupported type")

    allowed = {"type", "enum"}
    if type_name == "object":
        allowed.update({"properties", "required", "additionalProperties"})
    elif type_name == "array":
        allowed.add("items")
    elif type_name == "string":
        allowed.add("maxLength")
    elif type_name in {"integer", "number"}:
        allowed.update({"minimum", "maximum"})
    unknown = set(schema) - allowed
    if unknown:
        raise RoleToolProtocolError("Tool parameter schema contains unsupported keywords")

    normalized: dict[str, Any] = {"type": type_name}
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, (list, tuple)) or not enum:
            raise RoleToolProtocolError("Tool enum must be a non-empty array")
        _require_json(enum, "enum")
        if any(not _matches_type(item, type_name) for item in enum):
            raise RoleToolProtocolError("Tool enum values must match the schema type")
        normalized["enum"] = list(enum)

    if type_name == "object":
        additional = schema.get("additionalProperties")
        if additional is not False:
            raise RoleToolProtocolError("Tool object schemas require additionalProperties=false")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise RoleToolProtocolError("Tool object properties must be an object")
        normalized_properties = {}
        for name, property_schema in properties.items():
            if not isinstance(name, str) or not name:
                raise RoleToolProtocolError("Tool property names must be non-empty strings")
            normalized_properties[name] = _normalize_schema(property_schema)
        required = schema.get("required", [])
        if not isinstance(required, (list, tuple)) or any(
            not isinstance(name, str) or not name for name in required
        ):
            raise RoleToolProtocolError("Tool required properties must be strings")
        if len(set(required)) != len(required) or not set(required).issubset(properties):
            raise RoleToolProtocolError("Tool required properties must be declared")
        normalized["properties"] = normalized_properties
        if required:
            normalized["required"] = list(required)
        normalized["additionalProperties"] = False
    elif type_name == "array":
        if "items" not in schema:
            raise RoleToolProtocolError("Tool array schemas require items")
        normalized["items"] = _normalize_schema(schema["items"])
    elif type_name == "string" and "maxLength" in schema:
        max_length = schema["maxLength"]
        if type(max_length) is not int or max_length < 0:
            raise RoleToolProtocolError("Tool string maxLength must be a non-negative integer")
        normalized["maxLength"] = max_length
    elif type_name in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        for bound in (minimum, maximum):
            if bound is not None and not _matches_type(bound, type_name):
                raise RoleToolProtocolError("Tool numeric bounds must match the schema type")
        if minimum is not None:
            normalized["minimum"] = minimum
        if maximum is not None:
            normalized["maximum"] = maximum
        if minimum is not None and maximum is not None and minimum > maximum:
            raise RoleToolProtocolError("Tool minimum cannot exceed maximum")

    if root and type_name != "object":
        raise RoleToolProtocolError("Tool parameter schema must be an object schema")
    return normalized


def _validate_value(value: Any, schema: Mapping[str, Any], path: str) -> None:
    _require_json(value, path)
    type_name = schema["type"]
    if not _matches_type(value, type_name):
        raise RoleToolProtocolError(f"{path} must be a {type_name}")
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise RoleToolProtocolError(f"{path} must be one of the declared enum values")

    if type_name == "object":
        required = schema.get("required", ())
        missing = [name for name in required if name not in value]
        if missing:
            raise RoleToolProtocolError(f"{path} is missing required properties")
        properties = schema["properties"]
        unknown = set(value) - set(properties)
        if unknown:
            raise RoleToolProtocolError(f"{path} contains undeclared properties")
        for name, item in value.items():
            _validate_value(item, properties[name], f"{path}.{name}")
    elif type_name == "array":
        for index, item in enumerate(value):
            _validate_value(item, schema["items"], f"{path}[{index}]")
    elif type_name == "string" and "maxLength" in schema:
        if len(value) > schema["maxLength"]:
            raise RoleToolProtocolError(f"{path} exceeds maxLength")
    elif type_name in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise RoleToolProtocolError(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise RoleToolProtocolError(f"{path} exceeds maximum")


@dataclass(frozen=True, slots=True)
class RoleToolBudget:
    max_calls: int = 5
    max_argument_bytes: int = 8192
    max_result_bytes: int = 16384
    max_total_result_bytes: int = 65536
    max_elapsed_seconds: float = 300.0

    def __post_init__(self) -> None:
        for name in (
            "max_calls",
            "max_argument_bytes",
            "max_result_bytes",
            "max_total_result_bytes",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise RoleToolProtocolError(f"{name} must be a positive integer")
        if (
            not isinstance(self.max_elapsed_seconds, (int, float))
            or isinstance(self.max_elapsed_seconds, bool)
            or not math.isfinite(self.max_elapsed_seconds)
            or self.max_elapsed_seconds <= 0
        ):
            raise RoleToolProtocolError("max_elapsed_seconds must be a positive finite number")


@dataclass(frozen=True, slots=True)
class RoleToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise RoleToolProtocolError("Tool definition name must be a non-empty string")
        if not isinstance(self.description, str) or not self.description:
            raise RoleToolProtocolError("Tool definition description must be a non-empty string")
        object.__setattr__(self, "parameters", _freeze(_normalize_schema(self.parameters, root=True)))

    def to_ollama(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _thaw(self.parameters),
            },
        }

    def validate_arguments(self, arguments: Mapping[str, Any]) -> None:
        if not isinstance(arguments, Mapping):
            raise RoleToolProtocolError("Tool arguments must be an object")
        _validate_value(arguments, self.parameters, "arguments")


@dataclass(frozen=True, slots=True)
class RoleToolCall:
    name: str
    arguments: Mapping[str, Any]
    round_index: int
    call_index: int
    call_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise RoleToolProtocolError("Tool call name must be a non-empty string")
        if not isinstance(self.arguments, Mapping):
            raise RoleToolProtocolError("Tool call arguments must be an object")
        if type(self.round_index) is not int or self.round_index < 0:
            raise RoleToolProtocolError("Tool call round index must be a non-negative integer")
        if type(self.call_index) is not int or self.call_index < 0:
            raise RoleToolProtocolError("Tool call index must be a non-negative integer")
        if self.call_id is not None and (
            not isinstance(self.call_id, str) or not self.call_id
        ):
            raise RoleToolProtocolError("Tool call id must be a non-empty string")
        _require_json(self.arguments, "arguments")
        object.__setattr__(self, "arguments", _freeze(self.arguments))

    @classmethod
    def from_ollama(
        cls,
        payload: Mapping[str, Any],
        round_index: int,
        call_index: int,
    ) -> "RoleToolCall":
        if not isinstance(payload, Mapping):
            raise RoleToolProtocolError("Ollama tool call must be an object")
        function = payload.get("function")
        if not isinstance(function, Mapping):
            raise RoleToolProtocolError("Ollama tool call function must be an object")
        name = function.get("name")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise RoleToolProtocolError("Ollama tool arguments must be valid JSON") from error
        return cls(name, arguments, round_index, call_index, payload.get("id"))

    def to_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "arguments": _thaw(self.arguments),
            "round_index": self.round_index,
            "call_index": self.call_index,
        }
        if self.call_id is not None:
            data["call_id"] = self.call_id
        return data


@dataclass(frozen=True, slots=True)
class RoleToolResult:
    success: bool
    content: str
    byte_size: int
    error: Optional[str] = None

    @classmethod
    def from_value(cls, value: Any) -> "RoleToolResult":
        content = stable_json_bytes(value).decode("utf-8")
        return cls(success=True, content=content, byte_size=len(content.encode("utf-8")))

    @classmethod
    def failure(cls, reason: str) -> "RoleToolResult":
        content = stable_json_bytes({"error": reason}).decode("utf-8")
        return cls(False, content, len(content.encode("utf-8")), reason)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "success": self.success,
            "content": self.content,
            "byte_size": self.byte_size,
        }
        if self.error is not None:
            data["error"] = self.error
        return data


@dataclass(frozen=True, slots=True)
class RoleToolInvocation:
    role_name: str
    call: RoleToolCall
    result: RoleToolResult
    allowed: bool
    reason: str
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_name": self.role_name,
            "call": self.call.to_dict(),
            "result": self.result.to_dict(),
            "allowed": self.allowed,
            "reason": self.reason,
            "elapsed_seconds": self.elapsed_seconds,
        }
