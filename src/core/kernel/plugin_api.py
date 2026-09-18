"""Lightweight, child-safe public API for Python plugins."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

BrokerCall = Callable[[str, dict[str, Any]], Any]
AuditSink = Callable[[dict[str, Any]], None]

PLUGIN_API_AUDIT_LIMIT = 1000


class XiaoYiPluginAPI:
    """Delegate every external plugin operation through the active Broker."""

    def __init__(
        self,
        plugin_id: str,
        permissions: list[str],
        broker_call: BrokerCall | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self._permissions = set(permissions)
        self._audit_log: deque[dict[str, Any]] = deque(
            maxlen=PLUGIN_API_AUDIT_LIMIT
        )
        self._audit_lock = threading.Lock()
        self._broker_call = broker_call
        self._audit_sink = audit_sink

    def check_permission(self, permission: str) -> bool:
        return permission in self._permissions

    def log_access(self, api_name: str, args: dict[str, Any]) -> None:
        entry = {
            "plugin_id": self.plugin_id,
            "api": api_name,
            "args": str(args)[:200],
            "timestamp": datetime.now().isoformat(),
        }
        with self._audit_lock:
            self._audit_log.append(entry)
        if self._audit_sink is not None:
            self._audit_sink(entry.copy())

    def _broker_request(
        self,
        api_name: str,
        capability: str,
        args: dict[str, Any],
    ) -> Any:
        self.log_access(api_name, args)
        if self._broker_call is None:
            raise PermissionError("PLUGIN_BROKER_DENIED")
        result = self._broker_call(capability, args)
        if not hasattr(result, "allowed") or not hasattr(result, "error"):
            raise PermissionError("PLUGIN_BROKER_DENIED")
        if not result.allowed:
            raise PermissionError("PLUGIN_BROKER_DENIED")
        return result.result

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._broker_request(
            "get_config",
            "config.get",
            {"key": key, "default": default},
        )

    def read_file(self, path: str) -> Any:
        return self._broker_request("read_file", "file.read", {"path": path})

    def list_dir(self, path: str = ".") -> Any:
        return self._broker_request("list_dir", "file.list", {"path": path})

    def emit_event(self, event_type: str, payload: Any) -> Any:
        return self._broker_request(
            "emit_event",
            "event.emit",
            {"event_type": event_type, "payload": payload},
        )

    def call_llm(self, prompt: str, model: str = "default") -> Any:
        return self._broker_request(
            "call_llm",
            "llm.call",
            {"prompt": prompt, "model": model},
        )

    def get_url(self, url: str) -> Any:
        return self._broker_request(
            "get_url",
            "network.get",
            {"url": url},
        )

    def get_system_stats(self) -> Any:
        return self._broker_request("get_system_stats", "system.stats", {})

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or limit < 0:
            raise ValueError("Audit log limit must be a non-negative integer")
        if limit == 0:
            return []
        with self._audit_lock:
            return [entry.copy() for entry in list(self._audit_log)[-limit:]]
