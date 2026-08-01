"""Child-only JSON Lines Plugin Worker entrypoint."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
from typing import Any, BinaryIO, Mapping
import uuid


_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from core.contracts.plugin_worker_protocol import (
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
from core.kernel.plugin_sdk import XiaoYiPluginAPI


_LIFECYCLE_ERROR = "PLUGIN_LIFECYCLE_FAILED"
_MODULE_NAME = re.compile(r"[^A-Za-z0-9_]")


class _BrokerProtocolError(RuntimeError):
    """Raised when the parent violates the active Broker exchange contract."""


class PluginWorkerServer:
    """Run one Plugin module in a child process without constructing Core services."""

    def __init__(
        self,
        stdin: BinaryIO,
        stdout: BinaryIO,
        stderr: BinaryIO,
        plugin_root: Path | str,
    ) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._plugin_root = Path(plugin_root).resolve()
        self._worker_id = f"worker-{uuid.uuid4().hex}"
        self._module: Any = None
        self._module_name = ""
        self._plugin_id = ""
        self._permissions: tuple[str, ...] = ()
        self._generation = 0
        self._active_request_id = ""
        self._broker_call_count = 0
        self._audit: list[dict[str, Any]] = []

    @property
    def module(self) -> Any:
        """Expose the child-local module for direct unit tests only."""
        return self._module

    def hello(self) -> PluginWorkerHello:
        return PluginWorkerHello(worker_id=self._worker_id, pid=self._pid())

    def serve(self) -> int:
        """Emit one hello and handle lifecycle requests until shutdown or EOF."""
        self._write_message(self.hello())
        while True:
            line = self._read_line()
            if not line:
                return 0
            try:
                message = decode_message(line)
            except PluginWorkerProtocolError:
                return 1
            if not isinstance(message, PluginLifecycleRequest):
                return 1
            result = self.request(message)
            self._write_message(result)
            if message.action is LifecycleAction.SHUTDOWN:
                return 0

    def request(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        """Handle one already-decoded lifecycle request in the child process."""
        if not isinstance(request, PluginLifecycleRequest):
            raise TypeError("request must be a PluginLifecycleRequest")
        self._active_request_id = request.request_id
        self._broker_call_count = 0
        try:
            if request.action is LifecycleAction.LOAD:
                return self._load(request)
            if request.action is LifecycleAction.SHUTDOWN:
                return self._success(request, "unloaded")
            if self._module is None or request.plugin_id != self._plugin_id:
                return self._failure(request)
            if request.action is LifecycleAction.ACTIVATE:
                return self._activate(request)
            if request.action is LifecycleAction.DEACTIVATE:
                return self._deactivate(request)
            if request.action is LifecycleAction.CLEANUP:
                return self._cleanup(request)
        except BaseException:
            return self._failure(request)
        return self._failure(request)

    def _load(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        if self._module is not None:
            return self._failure(request)
        try:
            spec = PluginLoadSpec.from_dict(request.payload)
            entrypoint = self._resolve_entrypoint(spec.entry_point)
            module_name = self._worker_module_name(request.plugin_id, spec.generation)
            module_spec = importlib.util.spec_from_file_location(module_name, entrypoint)
            if module_spec is None or module_spec.loader is None:
                return self._failure(request)
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[module_name] = module
            module_spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(locals().get("module_name", ""), None)
            return self._failure(request)

        self._module = module
        self._module_name = module_name
        self._plugin_id = request.plugin_id
        self._permissions = spec.permissions
        self._generation = spec.generation
        return self._success(request, "loaded")

    def _activate(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        activate = getattr(self._module, "activate", None)
        if activate is None or not callable(activate):
            return self._failure(request)
        api = XiaoYiPluginAPI(
            self._plugin_id,
            list(self._permissions),
            broker_call=self._broker_call,
            audit_sink=self._record_audit,
        )
        try:
            activate(api)
        except BaseException:
            return self._failure(request)
        return self._success(request, "enabled")

    def _deactivate(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        deactivate = getattr(self._module, "deactivate", None)
        if deactivate is not None:
            if not callable(deactivate):
                return self._failure(request)
            try:
                deactivate()
            except BaseException:
                return self._failure(request)
        return self._success(request, "disabled")

    def _cleanup(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        cleanup = getattr(self._module, "cleanup", None)
        if cleanup is not None:
            if not callable(cleanup):
                return self._failure(request)
            try:
                cleanup()
            except BaseException:
                return self._failure(request)
        return self._success(request, "unloaded")

    def _broker_call(
        self,
        capability: str,
        arguments: Mapping[str, Any],
    ) -> PluginBrokerResult:
        self._broker_call_count += 1
        request = PluginBrokerRequest(
            request_id=self._active_request_id,
            call_id=f"broker-{self._broker_call_count}",
            plugin_id=self._plugin_id,
            capability=capability,
            arguments=arguments,
        )
        self._write_message(request)
        line = self._read_line()
        if not line:
            raise _BrokerProtocolError("missing Broker result")
        try:
            result = decode_message(line)
        except PluginWorkerProtocolError as exc:
            raise _BrokerProtocolError("invalid Broker result") from exc
        if not isinstance(result, PluginBrokerResult):
            raise _BrokerProtocolError("Broker result kind is invalid")
        if (
            result.request_id != request.request_id
            or result.call_id != request.call_id
            or result.plugin_id != request.plugin_id
        ):
            raise _BrokerProtocolError("Broker result correlation is invalid")
        return result

    def _resolve_entrypoint(self, entry_point: str) -> Path:
        if not self._plugin_root.is_dir():
            raise ValueError("plugin root is not a directory")
        relative = Path(entry_point)
        if relative.is_absolute():
            raise ValueError("plugin entrypoint must be relative")
        candidate = self._plugin_root / relative
        if candidate.is_symlink():
            raise ValueError("plugin entrypoint must not be a symbolic link")
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self._plugin_root)
        except ValueError as exc:
            raise ValueError("plugin entrypoint escapes plugin root") from exc
        if not candidate.is_file():
            raise ValueError("plugin entrypoint must be a regular file")
        return candidate

    @staticmethod
    def _worker_module_name(plugin_id: str, generation: int) -> str:
        safe_plugin_id = _MODULE_NAME.sub("_", plugin_id)
        return f"_jarvis_plugin_{safe_plugin_id}_{generation}"

    def _success(self, request: PluginLifecycleRequest, status: str) -> PluginLifecycleResult:
        return PluginLifecycleResult(
            request_id=request.request_id,
            plugin_id=request.plugin_id,
            success=True,
            status=status,
            error="",
            audit=tuple(self._audit[-100:]),
        )

    def _failure(self, request: PluginLifecycleRequest) -> PluginLifecycleResult:
        return PluginLifecycleResult(
            request_id=request.request_id,
            plugin_id=request.plugin_id,
            success=False,
            status="error",
            error=_LIFECYCLE_ERROR,
            audit=tuple(self._audit[-100:]),
        )

    def _record_audit(self, entry: Mapping[str, Any]) -> None:
        api = entry.get("api")
        if not isinstance(api, str):
            return
        self._audit.append(
            {
                "plugin_id": self._plugin_id,
                "api": api,
            }
        )
        if len(self._audit) > 100:
            del self._audit[:-100]

    def _read_line(self) -> bytes:
        line = self._stdin.readline(65_537)
        if isinstance(line, str):
            line = line.encode("utf-8")
        return line

    def _write_message(self, message: object) -> None:
        line = encode_message(message)  # type: ignore[arg-type]
        self._stdout.write(line)
        flush = getattr(self._stdout, "flush", None)
        if callable(flush):
            flush()

    @staticmethod
    def _pid() -> int:
        try:
            import os

            return os.getpid()
        except Exception:
            return 1


def main() -> int:
    """Run the trusted child entrypoint with the current directory as Plugin root."""
    plugin_root = Path.cwd().resolve()
    for location in (str(_SOURCE_ROOT), str(plugin_root)):
        if location not in sys.path:
            sys.path.insert(0, location)
    server = PluginWorkerServer(
        sys.stdin.buffer,
        sys.stdout.buffer,
        sys.stderr.buffer,
        plugin_root,
    )
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
