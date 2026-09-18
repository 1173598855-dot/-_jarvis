"""Manifest discovery and parent-owned coordination for isolated plugins."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any

from adapters.subprocess_plugin_runtime import (
    PluginRuntimeError,
    SubprocessPluginRuntime,
)
from core.contracts.plugin_worker_protocol import (
    LifecycleAction,
    PluginLoadSpec,
    redact_protocol_error,
)

from .event_bus import EventBus
from .plugin_api import XiaoYiPluginAPI
from .plugin_broker import FIRST_PARTY_EVENT_GRANTS, PluginBroker

logger = logging.getLogger(__name__)

PLUGIN_API_VERSION = "1.0.0"
_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ERROR_LIMIT = 512
MAX_PLUGIN_MANIFEST_BYTES = 64 * 1024
MAX_PLUGIN_DISCOVERY_ENTRIES = 8_192


def _serialized_lifecycle_method(method: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize public lifecycle state transitions for one owner."""

    @wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)

    return wrapper


def _is_link_or_reparse(path: Path) -> bool:
    try:
        details = path.lstat()
    except OSError:
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(
        stat.S_ISLNK(details.st_mode)
        or getattr(details, "st_file_attributes", 0) & reparse_flag
    )


class PluginStatus(Enum):
    """Stable public plugin lifecycle states."""

    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    UNLOADED = "unloaded"


class RuntimeType(Enum):
    """Discoverable runtime identifiers; only PYTHON_WORKER is executable."""

    PYTHON_WORKER = "python_worker"
    PYTHON_UV = "python_uv"
    PYTHON_VENV = "python_venv"
    NODE_WORKER = "node_worker"
    NATIVE = "native"


@dataclass
class PluginManifest:
    """Repository plugin manifest."""

    name: str
    version: str
    description: str
    author: str = ""
    permissions: list[str] = field(default_factory=list)
    denied_apis: list[str] = field(
        default_factory=lambda: ["fs", "child_process", "network"]
    )
    runtime: str = RuntimeType.NATIVE.value
    sandbox: bool = True
    entry_point: str = ""
    dependencies: list[str] = field(default_factory=list)
    api_version: str = PLUGIN_API_VERSION
    plugin_id: str = ""

    def __post_init__(self) -> None:
        if type(self.plugin_id) is str and self.plugin_id == "":
            self.plugin_id = str(uuid.uuid4())[:8]


@dataclass(frozen=True, slots=True)
class _PluginLoadIdentity:
    """Immutable identity of one validated active load generation."""

    canonical_root: Path
    entry_point: str
    runtime: str
    permissions: tuple[str, ...]
    api_version: str
    generation: int


@dataclass
class PluginInstance:
    """Public lifecycle record with private ownership of one Worker generation."""

    manifest: PluginManifest
    status: PluginStatus
    module: Any = None
    error_message: str = ""
    loaded_at: str = ""
    last_activated: str = ""
    activation_count: int = 0
    generation: int = 0
    _runtime: Any = field(default=None, repr=False, compare=False)
    _load_identity: _PluginLoadIdentity | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def worker_pid(self) -> int:
        """Return a live Worker PID without exposing or trusting runtime internals."""
        runtime = self._runtime
        try:
            snapshot = runtime.snapshot
            if snapshot.termination_confirmed:
                return 0
            pid = snapshot.pid
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return 0
        return pid if type(pid) is int and pid > 0 else 0


PluginRuntimeFactory = Callable[[Path, PluginLoadSpec, PluginBroker], Any]


class PluginLoader:
    """Discover manifests and coordinate isolated runtime handles."""

    def __init__(
        self,
        plugins_dir: str | Path,
        broker: PluginBroker,
        runtime_factory: PluginRuntimeFactory = SubprocessPluginRuntime,
    ) -> None:
        if not isinstance(broker, PluginBroker):
            raise ValueError("broker must be a PluginBroker")
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._plugins_root = self.plugins_dir.resolve(strict=True)
        self._broker = broker
        self._runtime_factory = runtime_factory
        self._lifecycle_lock = threading.RLock()
        self._plugins: dict[str, PluginInstance] = {}
        self._manifests: list[PluginManifest] = []
        self._generations: dict[str, int] = {}

    @_serialized_lifecycle_method
    def discover_plugins(self) -> list[PluginManifest]:
        """Read manifests from direct, non-symlink plugin directories."""
        manifests: list[PluginManifest] = []
        try:
            candidates = self._bounded_discovery_candidates()
        except OverflowError:
            logger.error(
                "Plugin manifest discovery rejected: direct entry limit exceeded"
            )
            self._manifests = manifests
            return manifests
        except (OSError, UnicodeError):
            self._manifests = manifests
            return manifests
        for plugin_path in candidates:
            if _is_link_or_reparse(plugin_path) or not plugin_path.is_dir():
                continue
            try:
                root = self._validate_direct_root(plugin_path)
                manifest_file = plugin_path / "manifest.json"
                if _is_link_or_reparse(manifest_file) or not manifest_file.is_file():
                    continue
                data = self._read_bounded_manifest(manifest_file)
                if not isinstance(data, dict):
                    raise ValueError("manifest must be an object")
                manifests.append(self._manifest_from_repository_data(data, root))
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                RecursionError,
                TypeError,
                ValueError,
            ) as error:
                logger.error("Plugin manifest discovery failed for %s: %s", plugin_path, type(error).__name__)
        self._manifests = manifests
        return manifests

    def _bounded_discovery_candidates(self) -> list[Path]:
        """Collect and sort a bounded direct-entry snapshot."""
        candidates: list[Path] = []
        with os.scandir(self.plugins_dir) as entries:
            for entry in entries:
                if len(candidates) >= MAX_PLUGIN_DISCOVERY_ENTRIES:
                    raise OverflowError("plugin directory has too many entries")
                candidates.append(Path(entry.path))
        candidates.sort(key=lambda path: path.name)
        return candidates

    @staticmethod
    def _read_bounded_manifest(path: Path) -> Any:
        if path.stat().st_size > MAX_PLUGIN_MANIFEST_BYTES:
            raise ValueError("plugin manifest is too large")
        with path.open("rb") as handle:
            raw = handle.read(MAX_PLUGIN_MANIFEST_BYTES + 1)
        if len(raw) > MAX_PLUGIN_MANIFEST_BYTES:
            raise ValueError("plugin manifest is too large")
        return json.loads(raw.decode("utf-8"))

    @_serialized_lifecycle_method
    def load_plugin(self, manifest: PluginManifest) -> PluginInstance:
        """Start and load exactly one validated Worker generation."""
        self._validate_manifest(manifest)
        self._validate_sandbox_policy(manifest)
        root = self._root_for_manifest(manifest)
        entry_point = self._validated_entrypoint(root, manifest.entry_point)
        existing = self._plugins.get(manifest.plugin_id)
        if existing is not None:
            self._require_same_identity(existing, manifest, root, entry_point)
            return existing

        if manifest.runtime != RuntimeType.PYTHON_WORKER.value:
            instance = self._new_instance(
                manifest,
                PluginStatus.ERROR,
                root,
                entry_point,
                error_message="PLUGIN_RUNTIME_UNSUPPORTED",
            )
            self._plugins[manifest.plugin_id] = instance
            return instance

        generation = self._generations.get(manifest.plugin_id, 0) + 1
        self._generations[manifest.plugin_id] = generation
        load_spec = PluginLoadSpec(
            entry_point=entry_point,
            permissions=tuple(manifest.permissions),
            api_version=manifest.api_version,
            generation=generation,
        )
        runtime = None
        try:
            runtime = self._runtime_factory(root, load_spec, self._broker)
            snapshot = runtime.start()
            if (
                snapshot.plugin_id != manifest.plugin_id
                or snapshot.generation != generation
                or type(snapshot.pid) is not int
                or snapshot.pid < 1
            ):
                raise PluginRuntimeError(
                    "PLUGIN_RUNTIME_IDENTITY_MISMATCH",
                    "Worker identity did not match the requested generation",
                )
            result = runtime.invoke(LifecycleAction.LOAD)
            if not result.success or result.status != PluginStatus.LOADED.value:
                return self._store_load_error(
                    manifest,
                    root,
                    entry_point,
                    generation,
                    runtime,
                    self._result_error("PLUGIN_LOAD_FAILED", result),
                )
        except Exception as error:
            return self._store_load_error(
                manifest,
                root,
                entry_point,
                generation,
                runtime,
                self._exception_error(error),
            )
        except BaseException:
            self._retain_interrupted_load(
                manifest,
                root,
                entry_point,
                generation,
                runtime,
            )
            raise

        instance = self._new_instance(
            manifest,
            PluginStatus.LOADED,
            root,
            entry_point,
            generation=generation,
            runtime=runtime,
        )
        self._plugins[manifest.plugin_id] = instance
        logger.info("Plugin loaded in Worker: %s generation %s", manifest.plugin_id, generation)
        return instance

    @_serialized_lifecycle_method
    def enable_plugin(self, plugin_id: str) -> bool:
        instance = self._plugins.get(plugin_id)
        if instance is None:
            return False
        if instance.status is PluginStatus.ENABLED:
            return True
        if instance.status not in {PluginStatus.LOADED, PluginStatus.DISABLED}:
            return False
        if not self._invoke(instance, LifecycleAction.ACTIVATE, PluginStatus.ENABLED):
            return False
        instance.last_activated = datetime.now().isoformat()
        instance.activation_count += 1
        return True

    @_serialized_lifecycle_method
    def disable_plugin(self, plugin_id: str) -> bool:
        instance = self._plugins.get(plugin_id)
        if instance is None:
            return False
        if instance.status is PluginStatus.DISABLED:
            return True
        if instance.status is not PluginStatus.ENABLED:
            return False
        return self._invoke(instance, LifecycleAction.DEACTIVATE, PluginStatus.DISABLED)

    @_serialized_lifecycle_method
    def unload_plugin(self, plugin_id: str) -> bool:
        instance = self._plugins.get(plugin_id)
        if instance is None:
            return False
        runtime = instance._runtime
        if runtime is None:
            instance.status = PluginStatus.UNLOADED
            self._plugins.pop(plugin_id, None)
            return True

        cleanup_error = ""
        first_exception: BaseException | None = None
        try:
            try:
                cleanup_result = runtime.invoke(LifecycleAction.CLEANUP)
                if (
                    not cleanup_result.success
                    or cleanup_result.status != PluginStatus.UNLOADED.value
                ):
                    cleanup_error = self._result_error(
                        "PLUGIN_CLEANUP_FAILED", cleanup_result
                    )
            except Exception as error:
                cleanup_error = self._bounded_error(
                    "PLUGIN_CLEANUP_FAILED", self._exception_error(error)
                )
            except BaseException as error:
                first_exception = error
                cleanup_error = self._bounded_error(
                    "PLUGIN_CLEANUP_FAILED", self._exception_error(error)
                )
        finally:
            shutdown_success = False
            try:
                try:
                    result = runtime.invoke(LifecycleAction.SHUTDOWN)
                    shutdown_success = bool(
                        result.success
                        and result.status == PluginStatus.UNLOADED.value
                    )
                except Exception:
                    shutdown_success = False
                except BaseException as error:
                    if first_exception is None:
                        first_exception = error
            finally:
                try:
                    runtime.close()
                except Exception:
                    pass
                except BaseException as error:
                    if first_exception is None:
                        first_exception = error

        if not self._termination_confirmed(runtime):
            instance.status = PluginStatus.ERROR
            instance.error_message = "PLUGIN_WORKER_TERMINATION_UNCONFIRMED"
            result = False
        else:
            instance.status = PluginStatus.UNLOADED
            if cleanup_error:
                instance.error_message = cleanup_error
            elif shutdown_success:
                instance.error_message = ""
            else:
                instance.error_message = "PLUGIN_WORKER_SHUTDOWN_FAILED"
            instance._runtime = None
            self._plugins.pop(plugin_id, None)
            result = shutdown_success and not cleanup_error

        if first_exception is not None:
            raise first_exception
        return result

    @_serialized_lifecycle_method
    def close(self) -> None:
        """Attempt cleanup and shutdown for every owned Worker."""
        first_exception: BaseException | None = None
        for plugin_id in sorted(self._plugins):
            try:
                self.unload_plugin(plugin_id)
            except Exception as error:
                instance = self._plugins.get(plugin_id)
                if instance is not None and instance.status is not PluginStatus.ERROR:
                    instance.status = PluginStatus.ERROR
                    instance.error_message = self._exception_error(error)
            except BaseException as error:
                if first_exception is None:
                    first_exception = error
                instance = self._plugins.get(plugin_id)
                if instance is not None and instance.status is not PluginStatus.ERROR:
                    instance.status = PluginStatus.ERROR
                    instance.error_message = self._exception_error(error)
        if first_exception is not None:
            raise first_exception

    @_serialized_lifecycle_method
    def get_plugin(self, plugin_id: str) -> PluginInstance | None:
        return self._plugins.get(plugin_id)

    @_serialized_lifecycle_method
    def get_all_plugins(self) -> list[PluginInstance]:
        return list(self._plugins.values())

    @_serialized_lifecycle_method
    def get_plugins_by_status(self, status: PluginStatus) -> list[PluginInstance]:
        return [plugin for plugin in self._plugins.values() if plugin.status is status]

    def _validate_manifest(self, manifest: PluginManifest) -> None:
        if not isinstance(manifest, PluginManifest):
            raise ValueError("manifest must be a PluginManifest")
        required_strings = {
            "name": manifest.name,
            "version": manifest.version,
            "runtime": manifest.runtime,
            "entry_point": manifest.entry_point,
            "api_version": manifest.api_version,
        }
        for field_name, value in required_strings.items():
            if type(value) is not str or not value.strip():
                raise ValueError(f"plugin {field_name} must be a non-empty string")
        for field_name in ("description", "author"):
            if type(getattr(manifest, field_name)) is not str:
                raise ValueError(f"plugin {field_name} must be a string")
        if (
            type(manifest.plugin_id) is not str
            or not _PLUGIN_ID.fullmatch(manifest.plugin_id)
        ):
            raise ValueError("plugin_id is invalid")
        for field_name in ("permissions", "denied_apis", "dependencies"):
            values = getattr(manifest, field_name)
            if type(values) is not list or any(
                type(value) is not str or not value for value in values
            ):
                raise ValueError(
                    f"plugin {field_name} must be a list of non-empty strings"
                )
        if type(manifest.sandbox) is not bool:
            raise ValueError("plugin sandbox must be a boolean")
        dangerous = {"fs_write", "child_process", "network_all", "system_control"}
        if dangerous.intersection(manifest.permissions):
            raise ValueError("plugin requests a dangerous permission")

    def _manifest_from_repository_data(
        self,
        data: dict[str, Any],
        root: Path,
    ) -> PluginManifest:
        plugin_id = data.get("plugin_id")
        if type(plugin_id) is not str or not _PLUGIN_ID.fullmatch(plugin_id):
            raise ValueError("repository plugin_id is missing or invalid")
        manifest = PluginManifest(**data)
        self._validate_manifest(manifest)
        self._validate_sandbox_policy(manifest)
        if manifest.plugin_id != root.name:
            raise ValueError("plugin root identity does not match plugin_id")
        manifest._plugin_root = root
        return manifest

    def _validate_sandbox_policy(self, manifest: PluginManifest) -> None:
        if manifest.sandbox:
            missing = {"fs", "child_process", "network"} - set(manifest.denied_apis)
            if missing:
                raise ValueError("plugin sandbox policy is incomplete")

    def _validate_direct_root(self, requested: Path) -> Path:
        try:
            parent = requested.parent.resolve(strict=True)
            root = requested.resolve(strict=True)
        except OSError as error:
            raise ValueError("plugin root is unavailable") from error
        if parent != self._plugins_root:
            raise ValueError("plugin root must be a direct child")
        if _is_link_or_reparse(requested) or not requested.is_dir():
            raise ValueError("plugin root must be a non-linked directory")
        if root.parent != self._plugins_root:
            raise ValueError("plugin root escaped the configured directory")
        return root

    def _root_for_manifest(self, manifest: PluginManifest) -> Path:
        requested = getattr(manifest, "_plugin_root", None)
        if not isinstance(requested, Path):
            requested = self.plugins_dir / manifest.plugin_id
        root = self._validate_direct_root(requested)
        if root.name != manifest.plugin_id:
            raise ValueError("plugin root identity does not match plugin_id")
        return root

    @staticmethod
    def _validated_entrypoint(root: Path, raw_entrypoint: str) -> str:
        relative = Path(raw_entrypoint)
        if (
            relative.is_absolute()
            or not raw_entrypoint
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError("plugin entry point is invalid")
        original = root / relative
        current = root
        for part in relative.parts:
            current = current / part
            if _is_link_or_reparse(current):
                raise ValueError("plugin entry point must not use symlinks")
        try:
            entrypoint = original.resolve(strict=True)
            entrypoint.relative_to(root)
        except (OSError, ValueError) as error:
            raise ValueError("plugin entry point escaped its root") from error
        if not entrypoint.is_file() or entrypoint.suffix != ".py":
            raise ValueError("plugin entry point must be a Python file")
        return relative.as_posix()

    @staticmethod
    def _require_same_identity(
        instance: PluginInstance,
        manifest: PluginManifest,
        root: Path,
        entry_point: str,
    ) -> None:
        identity = instance._load_identity
        if identity is None:
            raise ValueError("existing plugin load identity is unavailable")
        candidate = _PluginLoadIdentity(
            canonical_root=root,
            entry_point=entry_point,
            runtime=manifest.runtime,
            permissions=tuple(manifest.permissions),
            api_version=manifest.api_version,
            generation=identity.generation,
        )
        runtime_generation = identity.generation
        if instance._runtime is not None:
            try:
                runtime_generation = instance._runtime.snapshot.generation
            except (AttributeError, OSError, RuntimeError) as error:
                raise ValueError("existing plugin runtime identity is unavailable") from error
        if (
            candidate != identity
            or instance.generation != identity.generation
            or runtime_generation != identity.generation
        ):
            raise ValueError("plugin identity changed for an existing plugin_id")

    @staticmethod
    def _termination_confirmed(runtime: Any) -> bool:
        try:
            return runtime.snapshot.termination_confirmed is True
        except BaseException:
            return False

    @staticmethod
    def _bounded_error(code: str, detail: str = "") -> str:
        raw = code if not detail else f"{code}: {detail}"
        return redact_protocol_error(raw)[:_ERROR_LIMIT]

    @classmethod
    def _exception_error(cls, error: BaseException) -> str:
        if isinstance(error, PluginRuntimeError):
            return cls._bounded_error(error.code, error.message)
        return cls._bounded_error("PLUGIN_RUNTIME_FAILURE", type(error).__name__)

    @classmethod
    def _result_error(cls, code: str, result: Any) -> str:
        detail = result.error if isinstance(getattr(result, "error", None), str) else "invalid result"
        return cls._bounded_error(code, detail)

    @staticmethod
    def _new_instance(
        manifest: PluginManifest,
        status: PluginStatus,
        root: Path,
        entry_point: str,
        *,
        error_message: str = "",
        generation: int = 0,
        runtime: Any = None,
    ) -> PluginInstance:
        return PluginInstance(
            manifest=manifest,
            status=status,
            module=None,
            error_message=error_message,
            loaded_at=datetime.now().isoformat(),
            generation=generation,
            _runtime=runtime,
            _load_identity=_PluginLoadIdentity(
                canonical_root=root,
                entry_point=entry_point,
                runtime=manifest.runtime,
                permissions=tuple(manifest.permissions),
                api_version=manifest.api_version,
                generation=generation,
            ),
        )

    def _store_load_error(
        self,
        manifest: PluginManifest,
        root: Path,
        entry_point: str,
        generation: int,
        runtime: Any,
        error_message: str,
    ) -> PluginInstance:
        retained_runtime, close_interrupt = self._close_failed_runtime(runtime)
        if retained_runtime is not None:
            error_message = self._bounded_error(
                "PLUGIN_WORKER_TERMINATION_UNCONFIRMED", error_message
            )
        instance = self._new_instance(
            manifest,
            PluginStatus.ERROR,
            root,
            entry_point,
            error_message=error_message,
            generation=generation,
            runtime=retained_runtime,
        )
        self._plugins[manifest.plugin_id] = instance
        if close_interrupt is not None:
            raise close_interrupt
        return instance

    def _close_failed_runtime(
        self,
        runtime: Any,
    ) -> tuple[Any, BaseException | None]:
        if runtime is None:
            return None, None
        close_interrupt: BaseException | None = None
        try:
            runtime.close()
        except Exception:
            pass
        except BaseException as error:
            close_interrupt = error
        retained_runtime = (
            None if self._termination_confirmed(runtime) else runtime
        )
        return retained_runtime, close_interrupt

    def _retain_interrupted_load(
        self,
        manifest: PluginManifest,
        root: Path,
        entry_point: str,
        generation: int,
        runtime: Any,
    ) -> None:
        if runtime is None:
            return
        retained_runtime, _close_interrupt = self._close_failed_runtime(runtime)
        if retained_runtime is None:
            return
        self._plugins[manifest.plugin_id] = self._new_instance(
            manifest,
            PluginStatus.ERROR,
            root,
            entry_point,
            error_message="PLUGIN_WORKER_TERMINATION_UNCONFIRMED",
            generation=generation,
            runtime=retained_runtime,
        )

    def _invoke(
        self,
        instance: PluginInstance,
        action: LifecycleAction,
        success_status: PluginStatus,
    ) -> bool:
        runtime = instance._runtime
        if runtime is None:
            instance.status = PluginStatus.ERROR
            instance.error_message = "PLUGIN_RUNTIME_UNAVAILABLE"
            return False
        try:
            result = runtime.invoke(action)
        except Exception as error:
            instance.status = PluginStatus.ERROR
            instance.error_message = self._exception_error(error)
            return False
        if not result.success or result.status != success_status.value:
            instance.status = PluginStatus.ERROR
            instance.error_message = self._result_error(
                f"PLUGIN_{action.value.upper()}_FAILED", result
            )
            return False
        instance.status = success_status
        instance.error_message = ""
        return True

    def _create_sandbox(self, manifest: PluginManifest) -> dict[str, Any]:
        """Compatibility metadata only; this method never creates or executes a sandbox."""
        config: dict[str, Any] = {
            "runtime": manifest.runtime,
            "permissions": manifest.permissions,
            "denied_apis": manifest.denied_apis,
            "timeout": 30,
            "memory_limit": "128MB",
        }
        if manifest.runtime == RuntimeType.PYTHON_UV.value:
            venv_path = self.plugins_dir / manifest.plugin_id / "venv"
            config["venv_path"] = str(venv_path)
            config["python_path"] = str(venv_path / "bin" / "python")
        elif manifest.runtime == RuntimeType.NODE_WORKER.value:
            config["worker_type"] = "isolated"
        return config


class PluginManager:
    """Per-service owner of one Broker and its plugin Worker generations."""

    def __init__(
        self,
        plugins_dir: str | Path = "plugins",
        event_bus: EventBus | None = None,
        grants: Mapping[str, Iterable[str]] | None = None,
        runtime_factory: PluginRuntimeFactory = SubprocessPluginRuntime,
    ) -> None:
        self.event_bus = event_bus if event_bus is not None else EventBus()
        effective_grants = FIRST_PARTY_EVENT_GRANTS if grants is None else grants
        self.broker = PluginBroker(self.event_bus, grants=effective_grants)
        self.broker.register_event_emit_handler()
        self.broker.register_system_stats_handler()
        self.loader = PluginLoader(plugins_dir, self.broker, runtime_factory=runtime_factory)
        self.broker.register_file_read_handler()
        self.broker.register_file_list_handler()
        self.broker.register_config_get_handler()
        self._lifecycle_lock = threading.RLock()
        self._crash_count: dict[str, int] = {}

    @_serialized_lifecycle_method
    def discover(self) -> list[PluginManifest]:
        return self.loader.discover_plugins()

    @_serialized_lifecycle_method
    def load(self, manifest: PluginManifest) -> PluginInstance:
        return self.loader.load_plugin(manifest)

    @_serialized_lifecycle_method
    def enable(self, plugin_id: str) -> bool:
        result = self.loader.enable_plugin(plugin_id)
        if result:
            self._crash_count.pop(plugin_id, None)
        else:
            self._crash_count[plugin_id] = self._crash_count.get(plugin_id, 0) + 1
        return result

    @_serialized_lifecycle_method
    def disable(self, plugin_id: str) -> bool:
        return self.loader.disable_plugin(plugin_id)

    @_serialized_lifecycle_method
    def unload(self, plugin_id: str) -> bool:
        return self.loader.unload_plugin(plugin_id)

    @_serialized_lifecycle_method
    def close(self) -> None:
        self.loader.close()

    @_serialized_lifecycle_method
    def get_plugin(self, plugin_id: str) -> PluginInstance | None:
        return self.loader.get_plugin(plugin_id)

    @_serialized_lifecycle_method
    def get_all_plugins(self) -> list[PluginInstance]:
        return self.loader.get_all_plugins()

    @_serialized_lifecycle_method
    def load_all(self) -> dict[str, PluginInstance]:
        return {manifest.plugin_id: self.load(manifest) for manifest in self.discover()}


# Import compatibility only. Services should own their own PluginManager lifecycle.
global_plugin_manager = PluginManager()


__all__ = [
    "PLUGIN_API_VERSION",
    "PluginInstance",
    "PluginLoader",
    "PluginManager",
    "PluginManifest",
    "PluginStatus",
    "RuntimeType",
    "XiaoYiPluginAPI",
    "global_plugin_manager",
]
