"""Parent-owned, default-deny capability broker for Plugin workers."""

from __future__ import annotations

from collections import deque
import json
import re
import threading
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from core.contracts.plugin_worker_protocol import (
    PluginBrokerRequest,
    PluginBrokerResult,
    PluginWorkerProtocolError,
    redact_protocol_error,
    stable_json_bytes,
)
from core.kernel.event_bus import Event, EventBus


MAX_BROKER_CALLS = 32
MAX_BROKER_EXCHANGE_BYTES = 65_536
MAX_BROKER_AUDIT_ENTRIES = 100
MAX_EVENT_PAYLOAD_BYTES = 16_384

PLUGIN_BROKER_DENIED = "PLUGIN_BROKER_DENIED"
PLUGIN_BROKER_HANDLER_FAILED = "PLUGIN_BROKER_HANDLER_FAILED"

MANIFEST_PERMISSION_BY_CAPABILITY = MappingProxyType({"event.emit": "event_bus"})
FIRST_PARTY_EVENT_GRANTS = MappingProxyType(
    {
        "event-logger": frozenset({"event.emit"}),
        "plugin-template": frozenset({"event.emit"}),
    }
)

_EVENT_TYPE = re.compile(r"^plugin\.[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")

BrokerHandler = Callable[[PluginBrokerRequest], object]
BrokerArgumentValidator = Callable[[Mapping[str, Any]], bool]


class PluginBroker:
    """Authorize Plugin capability calls in the Core process."""

    def __init__(
        self,
        event_bus: EventBus,
        grants: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        if not isinstance(event_bus, EventBus):
            raise TypeError("event_bus must be an EventBus")
        self._event_bus = event_bus
        self._grants = {
            plugin_id: frozenset(capabilities)
            for plugin_id, capabilities in (grants or {}).items()
        }
        self._handlers: dict[str, tuple[BrokerHandler, BrokerArgumentValidator | None]] = {}
        self._audit: deque[dict[str, object]] = deque(maxlen=MAX_BROKER_AUDIT_ENTRIES)
        self._active_generations: dict[str, int] = {}
        self._generation_lock = threading.Lock()

    def register_handler(
        self,
        capability: str,
        handler: BrokerHandler,
        *,
        validator: BrokerArgumentValidator | None = None,
    ) -> None:
        if capability not in MANIFEST_PERMISSION_BY_CAPABILITY:
            raise ValueError("capability is not declared by the Plugin Broker")
        if not callable(handler):
            raise TypeError("handler must be callable")
        if validator is not None and not callable(validator):
            raise TypeError("validator must be callable")
        self._handlers[capability] = (handler, validator)

    def register_event_emit_handler(self) -> None:
        self.register_handler(
            "event.emit",
            self._handle_event_emit,
            validator=self._validate_event_emit_arguments,
        )

    def begin_lifecycle(
        self,
        plugin_id: str,
        request_id: str,
        declared_permissions: Iterable[str],
        generation: int,
    ) -> "PluginBrokerSession":
        session = PluginBrokerSession(
            self,
            plugin_id,
            request_id,
            frozenset(declared_permissions),
            generation,
        )
        with self._generation_lock:
            current = self._active_generations.get(plugin_id)
            if current is None or generation > current:
                self._active_generations[plugin_id] = generation
        return session

    def audit_log(self) -> list[dict[str, object]]:
        """Return a bounded detached copy of stable, redacted audit entries."""
        return [
            json.loads(stable_json_bytes(entry).decode("utf-8"))
            for entry in self._audit
        ]

    def _record(
        self,
        request: PluginBrokerRequest,
        *,
        allowed: bool,
        code: str,
    ) -> None:
        self._audit.append(
            {
                "plugin_id": redact_protocol_error(request.plugin_id),
                "request_id": redact_protocol_error(request.request_id),
                "call_id": redact_protocol_error(request.call_id),
                "capability": redact_protocol_error(request.capability),
                "allowed": allowed,
                "code": code,
            }
        )

    def _is_current_generation(self, plugin_id: str, generation: int) -> bool:
        with self._generation_lock:
            return self._active_generations.get(plugin_id) == generation

    @staticmethod
    def _validate_event_emit_arguments(arguments: Mapping[str, Any]) -> bool:
        if set(arguments) != {"event_type", "payload"}:
            return False
        event_type = arguments["event_type"]
        if not isinstance(event_type, str) or not _EVENT_TYPE.fullmatch(event_type):
            return False
        try:
            payload_bytes = stable_json_bytes(arguments["payload"])
        except PluginWorkerProtocolError:
            return False
        return len(payload_bytes) <= MAX_EVENT_PAYLOAD_BYTES

    def _handle_event_emit(self, request: PluginBrokerRequest) -> dict[str, bool]:
        arguments = request.arguments
        self._event_bus.publish(
            Event(
                event_type=arguments["event_type"],
                source=f"plugin:{request.plugin_id}",
                data=arguments["payload"],
            )
        )
        return {"emitted": True}


class PluginBrokerSession:
    """One lifecycle request's bounded, correlated Broker conversation."""

    def __init__(
        self,
        broker: PluginBroker,
        plugin_id: str,
        request_id: str,
        declared_permissions: frozenset[str],
        generation: int,
    ) -> None:
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("plugin_id must be non-empty")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be non-empty")
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be a positive integer")
        self._broker = broker
        self._plugin_id = plugin_id
        self._request_id = request_id
        self._declared_permissions = declared_permissions
        self.generation = generation
        self._call_ids: set[str] = set()
        self._calls = 0
        self._exchange_bytes = 0

    def handle(self, request: PluginBrokerRequest) -> PluginBrokerResult:
        if not self._broker._is_current_generation(self._plugin_id, self.generation):
            return self._deny(request)
        if (
            request.plugin_id != self._plugin_id
            or request.request_id != self._request_id
            or request.call_id in self._call_ids
        ):
            return self._deny(request)

        self._call_ids.add(request.call_id)
        self._calls += 1
        if self._calls > MAX_BROKER_CALLS:
            return self._deny(request)

        try:
            argument_bytes = stable_json_bytes(request.arguments)
        except PluginWorkerProtocolError:
            return self._deny(request)
        if self._exchange_bytes + len(argument_bytes) > MAX_BROKER_EXCHANGE_BYTES:
            return self._deny(request)
        self._exchange_bytes += len(argument_bytes)

        permission = MANIFEST_PERMISSION_BY_CAPABILITY.get(request.capability)
        if permission is None or permission not in self._declared_permissions:
            return self._deny(request)
        if request.capability not in self._broker._grants.get(self._plugin_id, frozenset()):
            return self._deny(request)

        registration = self._broker._handlers.get(request.capability)
        if registration is None:
            return self._deny(request)
        handler, validator = registration
        if validator is not None:
            try:
                if not validator(request.arguments):
                    return self._deny(request)
            except Exception:
                return self._handler_failed(request)

        try:
            value = handler(request)
            result_bytes = stable_json_bytes(value)
        except (PluginWorkerProtocolError, TypeError, ValueError):
            return self._handler_failed(request)
        except Exception:
            return self._handler_failed(request)
        if self._exchange_bytes + len(result_bytes) > MAX_BROKER_EXCHANGE_BYTES:
            return self._deny(request)
        self._exchange_bytes += len(result_bytes)

        result = PluginBrokerResult(
            request_id=request.request_id,
            call_id=request.call_id,
            plugin_id=request.plugin_id,
            allowed=True,
            result=value,
            error="",
        )
        self._broker._record(request, allowed=True, code="")
        return result

    def _deny(self, request: PluginBrokerRequest) -> PluginBrokerResult:
        result = PluginBrokerResult(
            request_id=request.request_id,
            call_id=request.call_id,
            plugin_id=request.plugin_id,
            allowed=False,
            result=None,
            error=PLUGIN_BROKER_DENIED,
        )
        self._broker._record(request, allowed=False, code=PLUGIN_BROKER_DENIED)
        return result

    def _handler_failed(self, request: PluginBrokerRequest) -> PluginBrokerResult:
        result = PluginBrokerResult(
            request_id=request.request_id,
            call_id=request.call_id,
            plugin_id=request.plugin_id,
            allowed=False,
            result=None,
            error=PLUGIN_BROKER_HANDLER_FAILED,
        )
        self._broker._record(
            request,
            allowed=False,
            code=PLUGIN_BROKER_HANDLER_FAILED,
        )
        return result
