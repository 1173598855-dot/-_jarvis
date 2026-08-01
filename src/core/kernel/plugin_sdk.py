"""Parent-side coordinator for isolated Plugin workers.

Plugin source code is never imported by this module.  The only executable
Plugin boundary is :class:`SubprocessPluginRuntime`, which owns a child
process and the versioned worker protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import logging
from pathlib import Path
import threading
import uuid
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from adapters.subprocess_plugin_runtime import (
    PluginRuntimeError,
    SubprocessPluginRuntime,
)
from core.contracts.plugin_worker_protocol import LifecycleAction, PluginLoadSpec, redact_protocol_error
from core.kernel.event_bus import EventBus
from core.kernel.plugin_broker import FIRST_PARTY_EVENT_GRANTS, PluginBroker


logger = logging.getLogger(__name__)
PLUGIN_API_VERSION = "1.0.0"
PLUGIN_RUNTIME_UNSUPPORTED = "PLUGIN_RUNTIME_UNSUPPORTED"
PLUGIN_WORKER_LIFECYCLE_FAILED = "PLUGIN_WORKER_LIFECYCLE_FAILED"


class PluginStatus(Enum):
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    UNLOADED = "unloaded"


class RuntimeType(Enum):
    """Known manifest values; only ``PYTHON_WORKER`` is executable."""

    PYTHON_UV = "python_uv"
    PYTHON_VENV = "python_venv"
    NODE_WORKER = "node_worker"
    NATIVE = "native"
    PYTHON_WORKER = "python_worker"


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str
    author: str = ""
    permissions: List[str] = field(default_factory=list)
    denied_apis: List[str] = field(default_factory=lambda: ["fs", "child_process", "network"])
    runtime: str = "native"
    sandbox: bool = True
    entry_point: str = ""
    dependencies: List[str] = field(default_factory=list)
    api_version: str = PLUGIN_API_VERSION
    plugin_id: str = ""

    def __post_init__(self) -> None:
        if not self.plugin_id:
            self.plugin_id = str(uuid.uuid4())[:8]


@dataclass
class PluginInstance:
    """Public lifecycle state plus private parent-owned Worker handle."""

    manifest: PluginManifest
    status: PluginStatus
    module: Any = None
    error_message: str = ""
    loaded_at: str = ""
    last_activated: str = ""
    activation_count: int = 0
    worker_pid: int | None = None
    generation: int = 0
    termination_confirmed: bool = False
    _runtime: Any = field(default=None, repr=False, compare=False)
    _identity: tuple[str, str] | None = field(default=None, repr=False, compare=False)


class XiaoYiPluginAPI:
    """Worker-local restricted API that delegates every capability to Broker."""

    def __init__(
        self,
        plugin_id: str,
        permissions: List[str],
        broker_call: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        audit_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.plugin_id = plugin_id
        self._permissions = set(permissions)
        self._audit_log: List[Dict[str, Any]] = []
        self._broker_call = broker_call
        self._audit_sink = audit_sink

    def check_permission(self, permission: str) -> bool:
        return permission in self._permissions

    def log_access(self, api_name: str, args: Dict[str, Any]) -> None:
        entry = {
            "plugin_id": self.plugin_id,
            "api": api_name,
            "args": str(args)[:200],
            "timestamp": datetime.now().isoformat(),
        }
        self._audit_log.append(entry)
        if self._audit_sink is not None:
            try:
                self._audit_sink(dict(entry))
            except Exception:
                pass

    def _call(self, permission: str, capability: str, arguments: Dict[str, Any]) -> Any:
        if not self.check_permission(permission):
            raise PermissionError(f"Plugin {self.plugin_id} lacks {permission} permission")
        self.log_access(capability, arguments)
        if self._broker_call is None:
            raise RuntimeError("Plugin Broker is unavailable")
        return self._broker_call(capability, arguments)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._call("system_config", "config.get", {"key": key, "default": default})

    def read_file(self, path: str) -> Any:
        return self._call("file_read", "file.read", {"path": path})

    def emit_event(self, event_type: str, payload: Any) -> Any:
        return self._call("event_bus", "event.emit", {"event_type": event_type, "payload": payload})

    def call_llm(self, prompt: str, model: str = "default") -> Any:
        return self._call("llm_access", "llm.call", {"prompt": prompt, "model": model})

    def get_system_stats(self) -> Any:
        return self._call("system_monitor", "system.stats", {})

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._audit_log[-limit:]


class PluginLoader:
    """Discover manifests and coordinate Worker handles without Plugin imports."""

    def __init__(
        self,
        plugins_dir: str | Path = "plugins",
        broker: PluginBroker | None = None,
        runtime_factory: Callable[..., Any] = SubprocessPluginRuntime,
    ) -> None:
        self.plugins_dir = Path(plugins_dir).resolve()
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        if broker is None:
            broker = PluginBroker(EventBus(), FIRST_PARTY_EVENT_GRANTS)
            broker.register_event_emit_handler()
        if not isinstance(broker, PluginBroker):
            raise TypeError("broker must be a PluginBroker")
        if not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable")
        self._broker = broker
        self._runtime_factory = runtime_factory
        self._plugins: Dict[str, PluginInstance] = {}
        self._sandbox_configs: Dict[str, Dict[str, Any]] = {}
        self._next_generation: Dict[str, int] = {}

    def discover_plugins(self) -> List[PluginManifest]:
        manifests: List[PluginManifest] = []
        for plugin_path in sorted(self.plugins_dir.iterdir(), key=lambda item: item.name):
            if plugin_path.is_symlink() or not plugin_path.is_dir():
                continue
            manifest_file = plugin_path / "manifest.json"
            if not manifest_file.is_file() or manifest_file.is_symlink():
                continue
            try:
                manifest = PluginManifest(**json.loads(manifest_file.read_text(encoding="utf-8")))
                if manifest.plugin_id != plugin_path.name:
                    raise ValueError("Plugin ID must match its direct root")
                manifests.append(manifest)
            except Exception:
                logger.warning("Ignoring invalid Plugin manifest in %s", plugin_path.name)
        return manifests

    def load_plugin(self, manifest: PluginManifest) -> PluginInstance:
        self._validate_manifest(manifest)
        self._validate_sandbox_policy(manifest)
        try:
            root = self._plugin_root(manifest.plugin_id)
        except PluginRuntimeError as exc:
            return self._error_instance(manifest, exc.code)
        identity = (str(root), manifest.entry_point)
        existing = self._plugins.get(manifest.plugin_id)
        if existing is not None:
            if existing._identity != identity:
                raise ValueError("Plugin identity changed while loaded")
            return existing
        if manifest.runtime != RuntimeType.PYTHON_WORKER.value:
            return self._error_instance(manifest, PLUGIN_RUNTIME_UNSUPPORTED, identity)

        runtime: Any = None
        try:
            generation = self._next_generation.get(manifest.plugin_id, 0) + 1
            spec = PluginLoadSpec(
                entry_point=manifest.entry_point,
                permissions=tuple(manifest.permissions),
                api_version=manifest.api_version,
                generation=generation,
            )
            runtime = self._runtime_factory(root, spec, self._broker)
            snapshot = runtime.start()
            result = runtime.invoke(LifecycleAction.LOAD)
            if not result.success or result.status != PluginStatus.LOADED.value:
                return self._failed_load_instance(
                    manifest,
                    identity,
                    generation,
                    runtime,
                    PLUGIN_WORKER_LIFECYCLE_FAILED,
                )
        except PluginRuntimeError as exc:
            return self._failed_load_instance(
                manifest,
                identity,
                self._next_generation.get(manifest.plugin_id, 0) + 1,
                runtime,
                exc.code,
            )
        except Exception:
            return self._failed_load_instance(
                manifest,
                identity,
                self._next_generation.get(manifest.plugin_id, 0) + 1,
                runtime,
                "PLUGIN_WORKER_START_FAILED",
            )

        instance = PluginInstance(
            manifest=manifest,
            status=PluginStatus.LOADED,
            module=None,
            loaded_at=datetime.now().isoformat(),
            worker_pid=snapshot.pid,
            generation=snapshot.generation,
            termination_confirmed=snapshot.termination_confirmed,
            _runtime=runtime,
            _identity=identity,
        )
        self._plugins[manifest.plugin_id] = instance
        self._next_generation[manifest.plugin_id] = generation
        return instance

    def enable_plugin(self, plugin_id: str) -> bool:
        instance = self._plugins.get(plugin_id)
        if instance is None:
            return False
        if instance.status is PluginStatus.ERROR and not instance.termination_confirmed:
            return False
        if instance.status is PluginStatus.ENABLED:
            return True
        return self._invoke_lifecycle(instance, LifecycleAction.ACTIVATE, PluginStatus.ENABLED, activate=True)

    def disable_plugin(self, plugin_id: str) -> bool:
        instance = self._plugins.get(plugin_id)
        if instance is None:
            return False
        return self._invoke_lifecycle(instance, LifecycleAction.DEACTIVATE, PluginStatus.DISABLED)

    def unload_plugin(self, plugin_id: str) -> bool:
        instance = self._plugins.get(plugin_id)
        if instance is None:
            return False
        runtime = instance._runtime
        if runtime is not None:
            try:
                runtime.invoke(LifecycleAction.CLEANUP)
            except Exception:
                pass
            try:
                runtime.close()
            except Exception:
                pass
            snapshot = getattr(runtime, "snapshot", None)
            if snapshot is not None:
                instance.worker_pid = snapshot.pid
                instance.termination_confirmed = bool(snapshot.termination_confirmed)
        if runtime is None or not instance.termination_confirmed:
            instance.status = PluginStatus.ERROR
            instance.error_message = "PLUGIN_WORKER_TERMINATION_UNCONFIRMED"
            return False
        instance.status = PluginStatus.UNLOADED
        del self._plugins[plugin_id]
        self._sandbox_configs.pop(plugin_id, None)
        return True

    def close(self) -> None:
        for plugin_id in list(self._plugins):
            try:
                self.unload_plugin(plugin_id)
            except Exception:
                logger.exception("Plugin shutdown failed: %s", plugin_id)

    def get_plugin(self, plugin_id: str) -> Optional[PluginInstance]:
        return self._plugins.get(plugin_id)

    def get_all_plugins(self) -> List[PluginInstance]:
        return list(self._plugins.values())

    def get_plugins_by_status(self, status: PluginStatus) -> List[PluginInstance]:
        return [instance for instance in self._plugins.values() if instance.status is status]

    def _invoke_lifecycle(
        self,
        instance: PluginInstance,
        action: LifecycleAction,
        expected_status: PluginStatus,
        *,
        activate: bool = False,
    ) -> bool:
        try:
            result = instance._runtime.invoke(action)
            if not result.success or result.status != expected_status.value:
                raise PluginRuntimeError(PLUGIN_WORKER_LIFECYCLE_FAILED)
        except PluginRuntimeError as exc:
            instance.status = PluginStatus.ERROR
            instance.error_message = exc.code
            return False
        except Exception:
            instance.status = PluginStatus.ERROR
            instance.error_message = PLUGIN_WORKER_LIFECYCLE_FAILED
            return False
        instance.status = expected_status
        if activate:
            instance.last_activated = datetime.now().isoformat()
            instance.activation_count += 1
        return True

    def _error_instance(
        self,
        manifest: PluginManifest,
        code: str,
        identity: tuple[str, str] | None = None,
        generation: int = 0,
    ) -> PluginInstance:
        return PluginInstance(
            manifest=manifest,
            status=PluginStatus.ERROR,
            module=None,
            error_message=redact_protocol_error(code),
            loaded_at=datetime.now().isoformat(),
            generation=generation,
            _identity=identity,
        )

    def _failed_load_instance(
        self,
        manifest: PluginManifest,
        identity: tuple[str, str],
        generation: int,
        runtime: Any,
        code: str,
    ) -> PluginInstance:
        if runtime is None:
            return self._error_instance(manifest, code, identity, generation)

        try:
            runtime.close()
        except Exception:
            pass

        snapshot = getattr(runtime, "snapshot", None)
        termination_confirmed = bool(
            snapshot is not None and getattr(snapshot, "termination_confirmed", False)
        )
        instance = self._error_instance(
            manifest,
            code if termination_confirmed else "PLUGIN_WORKER_TERMINATION_UNCONFIRMED",
            identity,
            getattr(snapshot, "generation", generation),
        )
        if snapshot is not None:
            instance.worker_pid = getattr(snapshot, "pid", None)
            instance.termination_confirmed = termination_confirmed
        if not termination_confirmed:
            instance._runtime = runtime
            self._plugins[manifest.plugin_id] = instance
            self._next_generation[manifest.plugin_id] = instance.generation
        return instance

    def _plugin_root(self, plugin_id: str) -> Path:
        candidate = self.plugins_dir / plugin_id
        if candidate.is_symlink() or not candidate.is_dir():
            raise PluginRuntimeError("PLUGIN_ROOT_INVALID", "Plugin root is invalid")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.plugins_dir)
        except ValueError as exc:
            raise PluginRuntimeError("PLUGIN_ROOT_INVALID", "Plugin root escapes configured directory") from exc
        if resolved.parent != self.plugins_dir:
            raise PluginRuntimeError("PLUGIN_ROOT_INVALID", "Plugin root must be a direct child")
        return resolved

    def _validate_manifest(self, manifest: PluginManifest) -> None:
        if not manifest.name:
            raise ValueError("Plugin name cannot be empty")
        if not manifest.version:
            raise ValueError("Plugin version cannot be empty")
        if not manifest.entry_point:
            raise ValueError("Plugin entry point cannot be empty")
        dangerous = {"fs_write", "child_process", "network_all", "system_control"}
        requested = set(manifest.permissions) & dangerous
        if requested:
            raise ValueError(f"Plugin requests dangerous permissions: {requested}")

    def _validate_sandbox_policy(self, manifest: PluginManifest) -> None:
        if manifest.sandbox:
            missing = {"fs", "child_process", "network"} - set(manifest.denied_apis)
            if missing:
                raise ValueError(f"Plugin sandbox policy misses denied APIs: {missing}")

    def _create_sandbox(self, manifest: PluginManifest) -> Dict[str, Any]:
        """Compatibility metadata only; it does not execute any runtime."""
        config = {
            "runtime": manifest.runtime,
            "permissions": list(manifest.permissions),
            "denied_apis": list(manifest.denied_apis),
            "timeout": 30,
        }
        if manifest.runtime == RuntimeType.PYTHON_UV.value:
            venv_path = self.plugins_dir / manifest.plugin_id / "venv"
            config.update({"venv_path": str(venv_path), "python_path": str(venv_path / "bin" / "python")})
        elif manifest.runtime == RuntimeType.NODE_WORKER.value:
            config["worker_type"] = "isolated"
        return config


class PluginManager:
    """Per-service Plugin owner.  Global access remains an import shim only."""

    _instance: Optional["PluginManager"] = None  # Legacy attribute, intentionally unused.

    def __init__(
        self,
        plugins_dir: str | Path = "plugins",
        event_bus: EventBus | None = None,
        grants: Mapping[str, Iterable[str]] | None = None,
        runtime_factory: Callable[..., Any] = SubprocessPluginRuntime,
    ) -> None:
        bus = event_bus or EventBus()
        broker = PluginBroker(bus, FIRST_PARTY_EVENT_GRANTS if grants is None else grants)
        broker.register_event_emit_handler()
        self.loader = PluginLoader(plugins_dir, broker, runtime_factory)
        self._crash_count: Dict[str, int] = {}
        self._max_crashes = 3

    def discover(self) -> List[PluginManifest]:
        return self.loader.discover_plugins()

    def load(self, manifest: PluginManifest) -> PluginInstance:
        return self.loader.load_plugin(manifest)

    def enable(self, plugin_id: str) -> bool:
        result = self.loader.enable_plugin(plugin_id)
        if result:
            self._crash_count.pop(plugin_id, None)
        else:
            self._crash_count[plugin_id] = self._crash_count.get(plugin_id, 0) + 1
            if self._crash_count[plugin_id] >= self._max_crashes:
                self.loader.disable_plugin(plugin_id)
        return result

    def disable(self, plugin_id: str) -> bool:
        return self.loader.disable_plugin(plugin_id)

    def unload(self, plugin_id: str) -> bool:
        return self.loader.unload_plugin(plugin_id)

    def close(self) -> None:
        self.loader.close()

    def get_plugin(self, plugin_id: str) -> Optional[PluginInstance]:
        return self.loader.get_plugin(plugin_id)

    def get_all_plugins(self) -> List[PluginInstance]:
        return self.loader.get_all_plugins()

    def load_all(self) -> Dict[str, PluginInstance]:
        return {manifest.plugin_id: self.load(manifest) for manifest in self.discover()}


class _LazyPluginManager:
    """Compatibility object for direct imports from older service entrypoints."""

    def __init__(self) -> None:
        self._manager: Optional[PluginManager] = None
        self._lock = threading.Lock()

    def _resolve(self) -> PluginManager:
        with self._lock:
            if self._manager is None:
                self._manager = PluginManager()
            return self._manager

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


global_plugin_manager = _LazyPluginManager()
