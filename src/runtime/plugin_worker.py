"""Child-only JSON Lines worker for one plugin lifecycle."""

from __future__ import annotations

# Standalone Worker path bootstrap must precede project-local imports.
# ruff: noqa: E402
import importlib.util
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO, Iterator, TextIO

_REPOSITORY_SRC = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT_FLAG = "--plugin-root"
if str(_REPOSITORY_SRC) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_SRC))


def _is_link_or_reparse(path: Path) -> bool:
    """True for symlinks and Windows reparse points such as junctions."""
    try:
        details = path.lstat()
    except (OSError, ValueError):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(
        stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & reparse_flag
    )


def _normalized_worker_directory(raw_path: str) -> Path:
    """Normalize an absolute Worker directory without resolving through links.

    `Path.resolve(strict=True)` calls `GetFinalPathNameByHandleW`, which a
    Windows AppContainer child is denied regardless of DACL, so the child
    rejects link components instead of following them.
    """
    candidate = Path(os.path.abspath(raw_path))
    if not candidate.is_absolute() or _is_link_or_reparse(candidate):
        raise OSError("Worker directory is linked or not absolute")
    if not candidate.is_dir():
        raise OSError("Worker directory is not a directory")
    return candidate


from core.contracts.plugin_worker_protocol import (
    MAX_PLUGIN_WORKER_LINE_BYTES,
    LifecycleAction,
    PluginBrokerRequest,
    PluginBrokerResult,
    PluginLifecycleRequest,
    PluginLifecycleResult,
    PluginLoadSpec,
    PluginWorkerHello,
    PluginWorkerProtocolError,
    decode_message,
    encode_message,
)
from core.kernel.plugin_api import XiaoYiPluginAPI
from core.kernel.worker_filesystem_isolation import (
    WorkerFilesystemIsolationError,
    isolate_worker_filesystem,
)
from core.kernel.worker_network_isolation import (
    WorkerNetworkIsolationError,
    isolate_worker_network,
)
from core.kernel.worker_resource_limits import (
    WorkerResourceLimitError,
    apply_worker_resource_limits,
)


class PluginWorkerServer:
    """Execute one plugin's lifecycle without constructing Core services."""

    def __init__(
        self,
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: TextIO,
        plugin_root: Path,
    ) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.plugin_root = Path(os.path.abspath(plugin_root))
        self.module: ModuleType | None = None
        self._plugin_id: str | None = None
        self._permissions: tuple[str, ...] = ()
        self._status = "unloaded"
        self._active_request: PluginLifecycleRequest | None = None
        self._call_count = 0
        self._action_audit: list[dict[str, Any]] = []
        self._shutdown = False

    def hello(self) -> PluginWorkerHello:
        return PluginWorkerHello(worker_id=f"worker-{os.getpid()}", pid=os.getpid())

    def serve(self) -> int:
        self._write(self.hello())
        while not self._shutdown:
            line = self.stdin.readline(MAX_PLUGIN_WORKER_LINE_BYTES + 1)
            if not line:
                return 0
            try:
                message = decode_message(line)
                if not isinstance(message, PluginLifecycleRequest):
                    raise PluginWorkerProtocolError("worker accepts lifecycle requests only")
                result = self.request(message)
            except PluginWorkerProtocolError:
                return 1
            self._write(result)
        return 0

    def request(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        if not isinstance(request, PluginLifecycleRequest):
            raise PluginWorkerProtocolError("worker request must be a lifecycle request")
        self._active_request = request
        self._call_count = 0
        self._action_audit = []
        try:
            with self._plugin_working_directory():
                if request.action is LifecycleAction.LOAD:
                    return self._load(request)
                if self._plugin_id != request.plugin_id:
                    return self._failure(request, "plugin_mismatch")
                if request.action is LifecycleAction.ACTIVATE:
                    return self._activate(request)
                if request.action is LifecycleAction.DEACTIVATE:
                    return self._deactivate(request)
                if request.action is LifecycleAction.CLEANUP:
                    return self._cleanup(request)
                if request.action is LifecycleAction.SHUTDOWN:
                    self._shutdown = True
                    self._status = "unloaded"
                    return self._success(request, "unloaded")
                return self._failure(request, "unsupported_lifecycle_action")
        except PermissionError:
            self._status = "error"
            return self._failure(request, "PLUGIN_BROKER_DENIED")
        except BaseException as error:
            self._status = "error"
            return self._failure(request, f"plugin_lifecycle_failed: {type(error).__name__}")
        finally:
            self._active_request = None

    @contextmanager
    def _plugin_working_directory(self) -> Iterator[None]:
        original = Path.cwd()
        try:
            os.chdir(self.plugin_root)
            yield
        finally:
            os.chdir(original)

    def _load(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        if self.module is not None or self._plugin_id is not None:
            return self._failure(request, "plugin_already_loaded")
        spec = PluginLoadSpec.from_dict(request.payload)
        entrypoint = self._entrypoint(spec.entry_point)
        module_name = self._module_name(request.plugin_id, spec.generation)
        module_spec = importlib.util.spec_from_file_location(module_name, entrypoint)
        if module_spec is None or module_spec.loader is None:
            return self._failure(request, "plugin_entrypoint_invalid")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        try:
            module_spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        self.module = module
        self._plugin_id = request.plugin_id
        self._permissions = spec.permissions
        self._status = "loaded"
        return self._success(request, "loaded")

    def _activate(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        if self.module is None or self._status not in {"loaded", "disabled"}:
            return self._failure(request, "activation_not_allowed")
        activate = getattr(self.module, "activate", None)
        if not callable(activate):
            return self._failure(request, "activate_missing")
        api = XiaoYiPluginAPI(
            request.plugin_id,
            self._permissions,
            self._broker_call,
            self._append_audit,
        )
        activate(api)
        self._status = "enabled"
        return self._success(request, "enabled")

    def _deactivate(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        if self.module is None or self._status != "enabled":
            return self._failure(request, "deactivation_not_allowed")
        deactivate = getattr(self.module, "deactivate", None)
        if callable(deactivate):
            deactivate()
        self._status = "disabled"
        return self._success(request, "disabled")

    def _cleanup(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        if self.module is None:
            return self._failure(request, "cleanup_not_allowed")
        cleanup = getattr(self.module, "cleanup", None)
        if callable(cleanup):
            cleanup()
        self._status = "unloaded"
        return self._success(request, "unloaded")

    def _entrypoint(self, raw_entrypoint: str) -> Path:
        relative = Path(raw_entrypoint)
        if (
            relative.is_absolute()
            or not raw_entrypoint
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise PluginWorkerProtocolError("plugin_entrypoint_invalid")
        candidate = self.plugin_root
        for part in relative.parts:
            candidate = candidate / part
            if _is_link_or_reparse(candidate):
                raise PluginWorkerProtocolError("plugin_entrypoint_invalid")
        candidate = Path(os.path.abspath(candidate))
        try:
            candidate.relative_to(self.plugin_root)
        except ValueError as error:
            raise PluginWorkerProtocolError("plugin_entrypoint_invalid") from error
        if not candidate.is_file() or candidate.suffix != ".py":
            raise PluginWorkerProtocolError("plugin_entrypoint_invalid")
        return candidate

    @staticmethod
    def _module_name(plugin_id: str, generation: int) -> str:
        return f"jarvis_plugin_id_{plugin_id.encode('utf-8').hex()}_generation_{generation}"

    def _broker_call(self, capability: str, arguments: dict[str, Any]) -> PluginBrokerResult:
        request = self._active_request
        if request is None:
            raise PluginWorkerProtocolError("broker call has no active lifecycle request")
        self._call_count += 1
        broker_request = PluginBrokerRequest(
            request_id=request.request_id,
            call_id=f"call-{self._call_count}",
            plugin_id=request.plugin_id,
            capability=capability,
            arguments=arguments,
        )
        self._write(broker_request)
        response = self.stdin.readline(MAX_PLUGIN_WORKER_LINE_BYTES + 1)
        if not response:
            raise PluginWorkerProtocolError("broker result is missing")
        message = decode_message(response)
        if not isinstance(message, PluginBrokerResult):
            raise PluginWorkerProtocolError("broker response must be a broker result")
        if (message.request_id, message.call_id, message.plugin_id) != (
            broker_request.request_id,
            broker_request.call_id,
            broker_request.plugin_id,
        ):
            raise PluginWorkerProtocolError("broker result correlation mismatch")
        return message

    def _append_audit(self, entry: dict[str, Any]) -> None:
        if len(self._action_audit) < 100:
            self._action_audit.append(entry)

    def _success(self, request: PluginLifecycleRequest, status: str) -> PluginLifecycleResult:
        return PluginLifecycleResult(
            request.request_id,
            request.plugin_id,
            True,
            status,
            "",
            tuple(self._action_audit),
        )

    def _failure(self, request: PluginLifecycleRequest, error: str) -> PluginLifecycleResult:
        return PluginLifecycleResult(
            request.request_id,
            request.plugin_id,
            False,
            "error",
            error,
            tuple(self._action_audit),
        )

    def _write(self, message: Any) -> None:
        self.stdout.write(encode_message(message))
        flush = getattr(self.stdout, "flush", None)
        if callable(flush):
            flush()


def main() -> int:
    arguments = sys.argv[1:]
    if len(arguments) != 2 or arguments[0] != _PLUGIN_ROOT_FLAG:
        return 2
    try:
        plugin_root = _normalized_worker_directory(arguments[1])
    except OSError:
        return 2
    try:
        apply_worker_resource_limits()
        isolate_worker_network()
        isolate_worker_filesystem(plugin_root)
    except (
        WorkerResourceLimitError,
        WorkerNetworkIsolationError,
        WorkerFilesystemIsolationError,
    ):
        return 2
    for location in (_REPOSITORY_SRC, plugin_root):
        value = str(location)
        if value not in sys.path:
            sys.path.insert(0, value)
    return PluginWorkerServer(sys.stdin.buffer, sys.stdout.buffer, sys.stderr, plugin_root).serve()


if __name__ == "__main__":
    raise SystemExit(main())
