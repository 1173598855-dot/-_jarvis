"""Parent-owned subprocess transport for one trusted plugin worker."""

from __future__ import annotations

import math
import os
import queue
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from core.contracts.plugin_worker_protocol import (
    MAX_PLUGIN_WORKER_LINE_BYTES,
    LifecycleAction,
    PluginBrokerRequest,
    PluginLifecycleRequest,
    PluginLifecycleResult,
    PluginLoadSpec,
    PluginWorkerHello,
    PluginWorkerProtocolError,
    ProtocolMessage,
    decode_message,
    encode_message,
)
from core.kernel.plugin_broker import PluginBroker
from core.kernel.process_containment import (
    ProcessContainmentError,
    ProcessTreeContainment,
    process_group_popen_kwargs,
)
from core.kernel.worker_macos_sandbox import (
    MacOSSandbox,
    WorkerMacOSSandboxError,
)
from core.kernel.worker_windows_container import (
    WindowsWorkerContainer,
    WorkerContainerError,
)

_REAL_SUBPROCESS_POPEN = subprocess.Popen
_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STDERR_LIMIT = 8 * 1024
_OUTPUT_QUEUE_LIMIT = 64
_PRESERVED_ENVIRONMENT = ("PATH", "PATHEXT", "SystemRoot", "WINDIR", "ComSpec")
_CONTAINER_PLATFORM = "nt"
_CONTAINER_SOURCE_STAGE = "src"
_SUCCESS_STATUS = {
    LifecycleAction.LOAD: "loaded",
    LifecycleAction.ACTIVATE: "enabled",
    LifecycleAction.DEACTIVATE: "disabled",
    LifecycleAction.CLEANUP: "unloaded",
    LifecycleAction.SHUTDOWN: "unloaded",
}


@dataclass(frozen=True, slots=True)
class PluginWorkerTimeouts:
    """Parent-owned deadlines, in seconds, for one Worker generation."""

    handshake: float = 5.0
    load: float = 10.0
    activate: float = 30.0
    deactivate: float = 30.0
    cleanup: float = 30.0
    shutdown: float = 5.0
    terminate: float = 1.0
    kill: float = 1.0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{field_name} timeout must be a positive number")

    def for_action(self, action: LifecycleAction) -> float:
        if not isinstance(action, LifecycleAction):
            raise ValueError("action must be a LifecycleAction")
        return float(getattr(self, action.value))


class PluginRuntimeError(RuntimeError):
    """Stable, bounded failure raised by the parent Worker transport."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message[:512]
        super().__init__(f"{self.code}: {self.message}")


@dataclass(frozen=True, slots=True)
class PluginRuntimeSnapshot:
    plugin_id: str
    pid: int
    generation: int
    termination_confirmed: bool


class _ContainerTempDirectoryView:
    """Compatibility view over the container-owned writable Worker root."""

    def __init__(self, path: Path) -> None:
        self.name = str(path)

    def cleanup(self) -> None:
        """The owning container performs actual cleanup after process exit."""


class SubprocessPluginRuntime:
    """Own one isolated Worker process for one Plugin and generation."""

    def __init__(
        self,
        plugin_root: str | Path,
        load_spec: PluginLoadSpec,
        broker: PluginBroker,
        timeouts: PluginWorkerTimeouts | None = None,
        *,
        os_isolation: bool | None = None,
        container_factory: Callable[[], WindowsWorkerContainer] | None = None,
        macos_sandbox_factory: Callable[[], MacOSSandbox] | None = None,
    ) -> None:
        if not isinstance(load_spec, PluginLoadSpec):
            raise ValueError("load_spec must be a PluginLoadSpec")
        if not isinstance(broker, PluginBroker):
            raise ValueError("broker must be a PluginBroker")
        if timeouts is not None and not isinstance(timeouts, PluginWorkerTimeouts):
            raise ValueError("timeouts must be PluginWorkerTimeouts")
        self._requested_root = Path(plugin_root)
        self._plugin_root: Path | None = None
        self._load_spec = load_spec
        self._broker = broker
        self._timeouts = timeouts or PluginWorkerTimeouts()
        self._plugin_id = self._requested_root.name
        self._container_factory = container_factory
        self._macos_sandbox_factory = macos_sandbox_factory
        self._os_isolation = os_isolation
        self._process: subprocess.Popen[bytes] | None = None
        self._process_containment: ProcessTreeContainment | None = None
        self._container: WindowsWorkerContainer | None = None
        self._macos_sandbox: MacOSSandbox | None = None
        self._worker_temp: tempfile.TemporaryDirectory[str] | None = None
        self._output_queue: queue.Queue[tuple[str, int, bytes | None]] = queue.Queue(
            maxsize=_OUTPUT_QUEUE_LIMIT
        )
        self._output_overflow = threading.Event()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_buffer = bytearray()
        self._stderr_lock = threading.Lock()
        self._operation_lock = threading.RLock()
        self._operation_active = threading.Event()
        self._termination_lock = threading.RLock()
        self._termination_started = threading.Event()
        self._transport_ready = threading.Event()
        self._transport_fault_lock = threading.Lock()
        self._transport_fault: tuple[str, str] | None = None
        self._handshake_hello_validated = False
        self._shutdown_response_eof_expected = False
        self._shutdown_response_eof_deferred = False
        self._containment_thread: threading.Thread | None = None
        self._request_number = 0
        self._started = False
        self._usable = False
        self._snapshot = PluginRuntimeSnapshot(
            self._plugin_id, 0, self._load_spec.generation, False
        )

    @property
    def snapshot(self) -> PluginRuntimeSnapshot:
        return self._snapshot

    @property
    def is_usable(self) -> bool:
        return (
            self._usable
            and not self._output_overflow.is_set()
            and self.process_is_alive()
        )

    def process_is_alive(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self) -> PluginRuntimeSnapshot:
        with self._operation_lock, self._operation_scope():
            if self._started:
                raise PluginRuntimeError(
                    "PLUGIN_WORKER_START_FAILED", "Worker generation was already started"
                )
            self._started = True
            self._plugin_root = self._validated_plugin_root()
            self._plugin_id = self._plugin_root.name
            try:
                self._broker.bind_file_read_root(
                    self._plugin_id, self._plugin_root
                )
            except (OSError, ValueError) as error:
                self._fatal(
                    "PLUGIN_WORKER_START_FAILED",
                    "Plugin file read root could not be bound",
                    cause=error,
                )
            self._snapshot = PluginRuntimeSnapshot(
                self._plugin_id, 0, self._load_spec.generation, False
            )
            source_root = Path(__file__).parent.parent
            worker = self._validated_worker_path(source_root)
            process: subprocess.Popen[bytes] | None = None
            try:
                process = (
                    self._spawn_os_isolated(source_root)
                    if self._should_use_os_isolation()
                    else self._spawn_direct(worker)
                )
                writable_root = self._owned_writable_root()
                if writable_root is not None:
                    self._worker_temp = _ContainerTempDirectoryView(
                        writable_root
                    )
                self._process = process
                self._process_containment = ProcessTreeContainment.attach(process)
                resume = getattr(process, "resume", None)
                if callable(resume):
                    resume()
            except (
                OSError,
                ProcessContainmentError,
                PluginRuntimeError,
                WorkerContainerError,
                WorkerMacOSSandboxError,
                subprocess.SubprocessError,
            ) as error:
                if process is None:
                    self._cleanup_worker_temp()
                    self._cleanup_os_sandbox()
                else:
                    self._process = process
                    try:
                        self._terminate_process()
                    finally:
                        close_spawn_handle = getattr(
                            process, "close_spawn_handle", None
                        )
                        if callable(close_spawn_handle):
                            close_spawn_handle()
                raise PluginRuntimeError(
                    "PLUGIN_WORKER_START_FAILED", "Worker process could not be started"
                ) from error

            self._snapshot = PluginRuntimeSnapshot(
                self._plugin_id, process.pid, self._load_spec.generation, False
            )
            self._transport_ready.set()
            try:
                self._start_readers(process)
            except RuntimeError as error:
                self._fatal(
                    "PLUGIN_WORKER_START_FAILED",
                    "Worker reader threads could not be started",
                    cause=error,
                )
            deadline = time.monotonic() + self._timeouts.handshake
            message = self._wait_for_message(deadline, handshake=True)
            if (
                not isinstance(message, PluginWorkerHello)
                or message.worker_id != f"worker-{message.pid}"
            ):
                self._fatal(
                    "PLUGIN_WORKER_HANDSHAKE_FAILED", "Worker handshake was invalid"
                )
            self._snapshot = PluginRuntimeSnapshot(
                self._plugin_id, message.pid, self._load_spec.generation, False
            )
            with self._transport_fault_lock:
                self._handshake_hello_validated = True
                fault = self._transport_fault
                if fault is None:
                    self._usable = True
            if fault is not None:
                self._raise_transport_fault()
            return self._snapshot

    def invoke(self, action: LifecycleAction) -> PluginLifecycleResult:
        with self._operation_lock, self._operation_scope():
            if not isinstance(action, LifecycleAction):
                raise ValueError("action must be a LifecycleAction")
            self._raise_transport_fault()
            if self._output_overflow.is_set():
                self._fatal(
                    "PLUGIN_WORKER_OUTPUT_LIMIT", "Worker output exceeded its limit"
                )
            if self._process is not None and self._process.poll() is not None:
                self._fatal("PLUGIN_WORKER_CRASHED", "Worker process exited unexpectedly")
            if not self._started or not self._usable:
                raise PluginRuntimeError(
                    "PLUGIN_WORKER_CRASHED", "Worker generation is not usable"
                )
            self._request_number += 1
            request_id = f"request-{self._load_spec.generation}-{self._request_number}"
            payload = self._load_spec.to_dict() if action is LifecycleAction.LOAD else {}
            request = PluginLifecycleRequest(
                request_id=request_id,
                plugin_id=self._plugin_id,
                action=action,
                payload=payload,
            )
            deadline = time.monotonic() + self._timeouts.for_action(action)
            session = None
            committed = False
            try:
                session = self._broker.begin_lifecycle(
                    self._plugin_id,
                    request_id,
                    self._load_spec.permissions,
                    self._load_spec.generation,
                    deadline=deadline,
                )
            except (TypeError, ValueError) as error:
                self._fatal(
                    "PLUGIN_WORKER_PROTOCOL_ERROR",
                    "Worker generation could not open a Broker session",
                    cause=error,
                )
            try:
                line = self._encode(request)
                if action is LifecycleAction.SHUTDOWN:
                    with self._transport_fault_lock:
                        self._shutdown_response_eof_expected = True
                        self._shutdown_response_eof_deferred = False
                self._write(line)

                while True:
                    message = self._wait_for_message(deadline)
                    if isinstance(message, PluginBrokerRequest):
                        if (
                            message.request_id != request_id
                            or message.plugin_id != self._plugin_id
                        ):
                            self._fatal(
                                "PLUGIN_WORKER_PROTOCOL_ERROR",
                                "Broker request correlation was invalid",
                            )
                        result = session.handle(message)
                        if time.monotonic() >= deadline:
                            self._fatal(
                                "PLUGIN_WORKER_TIMEOUT",
                                "Worker action exceeded its deadline",
                            )
                        self._write(self._encode(result))
                        continue
                    if not isinstance(message, PluginLifecycleResult):
                        self._fatal(
                            "PLUGIN_WORKER_PROTOCOL_ERROR",
                            "Worker returned an unexpected message",
                        )
                    self._validate_result(message, request_id, action)
                    if action is LifecycleAction.SHUTDOWN:
                        self._complete_shutdown_response(message.success)
                    if not message.success:
                        return message
                    if time.monotonic() >= deadline:
                        self._fatal(
                            "PLUGIN_WORKER_TIMEOUT",
                            "Worker action exceeded its deadline",
                        )
                    if action is LifecycleAction.SHUTDOWN:
                        confirmed = self._terminate_process()
                        if not confirmed:
                            raise PluginRuntimeError(
                                "PLUGIN_WORKER_TERMINATION_UNCONFIRMED",
                                "Worker process termination could not be confirmed",
                            )
                    if not session.commit_events():
                        self._fatal(
                            "PLUGIN_WORKER_TIMEOUT",
                            "Worker event commit exceeded its deadline",
                        )
                    committed = True
                    return message
            finally:
                if session is not None and not committed:
                    session.abort()

    def close(self) -> None:
        with self._operation_lock, self._operation_scope():
            self._usable = False
            if self._process is not None:
                self._terminate_process()
            else:
                self._cleanup_worker_temp()
                self._cleanup_os_sandbox()

    @contextmanager
    def _operation_scope(self) -> Iterator[None]:
        self._operation_active.set()
        try:
            yield
        finally:
            self._operation_active.clear()
            if self._transport_fault_value() is not None:
                self._schedule_transport_containment()

    def _spawn_direct(self, worker: Path) -> subprocess.Popen[bytes]:
        """Start the Worker without an OS boundary, as POSIX hosts still do."""
        self._worker_temp = tempfile.TemporaryDirectory(
            prefix="jarvis-plugin-worker-"
        )
        return subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-u",
                str(worker),
                "--plugin-root",
                str(self._plugin_root),
            ],
            cwd=str(worker.parent),
            env=self._sanitized_environment(self._worker_temp.name),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            close_fds=True,
            **process_group_popen_kwargs(),
        )

    def _spawn_os_isolated(self, source_root: Path) -> subprocess.Popen[bytes]:
        """Choose the parent-owned platform boundary selected for this Worker."""
        if self._macos_sandbox_factory is not None or sys.platform == "darwin":
            return self._spawn_macos_contained(source_root)
        return self._spawn_contained(source_root)

    def _should_use_os_isolation(self) -> bool:
        if self._os_isolation is not None:
            return bool(self._os_isolation)
        return (
            self._container_factory is not None
            or self._macos_sandbox_factory is not None
            or (
                os.name == _CONTAINER_PLATFORM
                or sys.platform == "darwin"
            )
            and subprocess.Popen is _REAL_SUBPROCESS_POPEN
        )

    def _spawn_macos_contained(self, source_root: Path) -> subprocess.Popen[bytes]:
        """Start the Worker through the parent-owned macOS Seatbelt sandbox."""
        if self._plugin_root is None:
            raise WorkerMacOSSandboxError("the Worker plugin root was not validated")
        factory = (
            MacOSSandbox.create
            if self._macos_sandbox_factory is None
            else self._macos_sandbox_factory
        )
        sandbox = factory()
        self._macos_sandbox = sandbox
        staged_source = sandbox.stage(source_root, _CONTAINER_SOURCE_STAGE)
        staged_plugin = sandbox.stage(self._plugin_root, self._plugin_id)
        worker = self._validated_worker_path(staged_source)
        return sandbox.spawn(
            [
                sys.executable,
                "-I",
                "-u",
                str(worker),
                "--plugin-root",
                str(staged_plugin),
            ],
            cwd=worker.parent,
            environment=self._sanitized_environment(str(sandbox.writable_root)),
            **process_group_popen_kwargs(),
        )

    def _spawn_contained(self, source_root: Path) -> subprocess.Popen[bytes]:
        """Start the Worker inside a parent-owned OS container.

        The child executes a read-only snapshot of the trusted Worker sources
        and the plugin, so the repository itself stays outside the container's
        read set. Broker file capabilities still resolve against the real
        plugin root in this parent process.
        """
        if self._plugin_root is None:
            raise WorkerContainerError("the Worker plugin root was not validated")
        factory = (
            WindowsWorkerContainer.create
            if self._container_factory is None
            else self._container_factory
        )
        container = factory()
        self._container = container
        staged_source = container.stage(source_root, _CONTAINER_SOURCE_STAGE)
        staged_plugin = container.stage(self._plugin_root, self._plugin_id)
        worker = self._validated_worker_path(staged_source)
        return container.spawn(
            [
                str(container.interpreter),
                "-I",
                "-u",
                str(worker),
                "--plugin-root",
                str(staged_plugin),
            ],
            cwd=worker.parent,
            environment=self._sanitized_environment(str(container.writable_root)),
            **process_group_popen_kwargs(),
        )

    def _validated_plugin_root(self) -> Path:
        try:
            root = self._requested_root.resolve(strict=True)
            parent = self._requested_root.parent.resolve(strict=True)
        except OSError as error:
            raise PluginRuntimeError(
                "PLUGIN_ROOT_INVALID", "Plugin root is not available"
            ) from error
        if (
            self._requested_root.is_symlink()
            or not root.is_dir()
            or root.parent != parent
            or root == root.parent
            or not _PLUGIN_ID.fullmatch(root.name)
        ):
            raise PluginRuntimeError(
                "PLUGIN_ROOT_INVALID", "Plugin root must be a regular direct child"
            )
        return root

    @staticmethod
    def _validated_worker_path(source_root: Path) -> Path:
        runtime_dir = source_root / "runtime"
        worker = runtime_dir / "plugin_worker.py"
        try:
            runtime_status = runtime_dir.lstat()
            worker_status = worker.lstat()
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (
                stat.S_ISLNK(runtime_status.st_mode)
                or not stat.S_ISDIR(runtime_status.st_mode)
                or getattr(runtime_status, "st_file_attributes", 0) & reparse_flag
                or stat.S_ISLNK(worker_status.st_mode)
                or not stat.S_ISREG(worker_status.st_mode)
                or getattr(worker_status, "st_file_attributes", 0) & reparse_flag
            ):
                raise OSError("trusted Worker path is linked or irregular")
            trusted_root = source_root.resolve(strict=True)
            resolved_runtime = runtime_dir.resolve(strict=True)
            resolved_worker = worker.resolve(strict=True)
        except OSError as error:
            raise PluginRuntimeError(
                "PLUGIN_WORKER_START_FAILED", "Worker process could not be started"
            ) from error
        if (
            resolved_runtime.parent != trusted_root
            or resolved_worker.parent != resolved_runtime
        ):
            raise PluginRuntimeError(
                "PLUGIN_WORKER_START_FAILED", "Worker process could not be started"
            )
        return resolved_worker

    @staticmethod
    def _sanitized_environment(worker_temp: str) -> dict[str, str]:
        parent_by_casefold = {key.casefold(): value for key, value in os.environ.items()}
        environment = {
            key: parent_by_casefold[key.casefold()]
            for key in _PRESERVED_ENVIRONMENT
            if key.casefold() in parent_by_casefold
        }
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONNOUSERSITE": "1",
                "TMP": worker_temp,
                "TEMP": worker_temp,
                "TMPDIR": worker_temp,
            }
        )
        return environment

    def _start_readers(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdout is None or process.stderr is None or process.stdin is None:
            self._fatal(
                "PLUGIN_WORKER_START_FAILED", "Worker pipes were not created"
            )
        generation = self._load_spec.generation
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(process.stdout, generation),
            name=f"plugin-worker-stdout-{process.pid}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(process.stderr,),
            name=f"plugin-worker-stderr-{process.pid}",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self, stream: BinaryIO, generation: int) -> None:
        try:
            while True:
                line = stream.readline(MAX_PLUGIN_WORKER_LINE_BYTES + 1)
                if not line:
                    self._observe_transport_fault(
                        "PLUGIN_WORKER_CRASHED",
                        "Worker process ended before a result",
                        eof=True,
                    )
                    self._put_output(("eof", generation, None))
                    return
                if len(line) > MAX_PLUGIN_WORKER_LINE_BYTES:
                    self._observe_transport_fault(
                        "PLUGIN_WORKER_OUTPUT_LIMIT",
                        "Worker output exceeded its limit",
                    )
                    self._output_overflow.set()
                    self._put_output(("overflow", generation, None))
                    return
                self._observe_handshake_hello(line)
                if not self._put_output(("line", generation, line)):
                    return
        except (OSError, ValueError):
            self._observe_transport_fault(
                "PLUGIN_WORKER_CRASHED", "Worker process ended before a result"
            )
            self._put_output(("reader_error", generation, None))

    def _put_output(self, event: tuple[str, int, bytes | None]) -> bool:
        try:
            self._output_queue.put_nowait(event)
        except queue.Full:
            self._observe_transport_fault(
                "PLUGIN_WORKER_OUTPUT_LIMIT", "Worker output exceeded its limit"
            )
            self._output_overflow.set()
            return False
        return True

    def _observe_transport_fault(
        self, code: str, message: str, *, eof: bool = False
    ) -> None:
        if not self._transport_ready.is_set():
            return
        should_contain = False
        with self._transport_fault_lock:
            if self._termination_started.is_set():
                return
            if eof and self._shutdown_response_eof_expected:
                self._shutdown_response_eof_deferred = True
                return
            if self._transport_fault is None:
                if (
                    code == "PLUGIN_WORKER_CRASHED"
                    and not self._handshake_hello_validated
                ):
                    code = "PLUGIN_WORKER_HANDSHAKE_FAILED"
                    message = "Worker handshake ended before hello"
                self._transport_fault = (code, message)
                self._usable = False
                should_contain = not self._operation_active.is_set()
        if should_contain:
            self._schedule_transport_containment()

    def _observe_handshake_hello(self, line: bytes) -> None:
        with self._transport_fault_lock:
            if self._handshake_hello_validated:
                return
        try:
            message = decode_message(line)
        except PluginWorkerProtocolError:
            return
        if (
            isinstance(message, PluginWorkerHello)
            and message.worker_id == f"worker-{message.pid}"
        ):
            with self._transport_fault_lock:
                self._handshake_hello_validated = True

    def _complete_shutdown_response(self, success: bool) -> None:
        should_contain = False
        with self._transport_fault_lock:
            deferred = self._shutdown_response_eof_deferred
            self._shutdown_response_eof_deferred = False
            if success:
                return
            self._shutdown_response_eof_expected = False
            if deferred and self._transport_fault is None:
                self._transport_fault = (
                    "PLUGIN_WORKER_CRASHED",
                    "Worker process ended before a result",
                )
                self._usable = False
                should_contain = not self._operation_active.is_set()
        if should_contain:
            self._schedule_transport_containment()

    def _transport_fault_value(self) -> tuple[str, str] | None:
        with self._transport_fault_lock:
            return self._transport_fault

    def _raise_transport_fault(self) -> None:
        fault = self._transport_fault_value()
        if fault is None:
            return
        self._terminate_process()
        raise PluginRuntimeError(*fault)

    def _schedule_transport_containment(self) -> None:
        with self._transport_fault_lock:
            if self._termination_started.is_set():
                return
            current = self._containment_thread
            if current is not None:
                return
            thread = threading.Thread(
                target=self._contain_transport_fault,
                name=f"plugin-worker-containment-{self._snapshot.pid}",
                daemon=True,
            )
            self._containment_thread = thread
        try:
            thread.start()
        except RuntimeError:
            with self._transport_fault_lock:
                if self._containment_thread is thread:
                    self._containment_thread = None
            self._terminate_process()

    def _contain_transport_fault(self) -> None:
        try:
            self._terminate_process()
        finally:
            with self._transport_fault_lock:
                if self._containment_thread is threading.current_thread():
                    self._containment_thread = None

    def _read_stderr(self, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(1024)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr_buffer.extend(chunk)
                    if len(self._stderr_buffer) > _STDERR_LIMIT:
                        del self._stderr_buffer[:-_STDERR_LIMIT]
        except (OSError, ValueError):
            return

    def _wait_for_message(self, deadline: float, handshake: bool = False):
        while True:
            self._raise_transport_fault()
            if self._output_overflow.is_set():
                self._fatal(
                    "PLUGIN_WORKER_OUTPUT_LIMIT", "Worker output exceeded its limit"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fatal(
                    "PLUGIN_WORKER_TIMEOUT",
                    "Worker handshake exceeded its deadline"
                    if handshake
                    else "Worker action exceeded its deadline",
                )
            try:
                event, generation, line = self._output_queue.get(timeout=remaining)
            except queue.Empty:
                self._fatal(
                    "PLUGIN_WORKER_TIMEOUT",
                    "Worker handshake exceeded its deadline"
                    if handshake
                    else "Worker action exceeded its deadline",
                )
            self._raise_transport_fault()
            if generation != self._load_spec.generation:
                continue
            if event == "overflow":
                self._fatal(
                    "PLUGIN_WORKER_OUTPUT_LIMIT", "Worker output exceeded its limit"
                )
            if event in {"eof", "reader_error"}:
                self._fatal(
                    "PLUGIN_WORKER_HANDSHAKE_FAILED" if handshake else "PLUGIN_WORKER_CRASHED",
                    "Worker handshake ended before hello"
                    if handshake
                    else "Worker process ended before a result",
                )
            if event != "line" or line is None:
                self._fatal(
                    "PLUGIN_WORKER_PROTOCOL_ERROR", "Worker transport event was invalid"
                )
            try:
                return decode_message(line)
            except PluginWorkerProtocolError as error:
                self._fatal(
                    "PLUGIN_WORKER_HANDSHAKE_FAILED"
                    if handshake
                    else "PLUGIN_WORKER_PROTOCOL_ERROR",
                    "Worker handshake was malformed"
                    if handshake
                    else "Worker message was malformed",
                    cause=error,
                )

    def _write(self, line: bytes) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            self._fatal("PLUGIN_WORKER_CRASHED", "Worker process is not writable")
        try:
            process.stdin.write(line)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            self._fatal(
                "PLUGIN_WORKER_CRASHED", "Worker process rejected its request", cause=error
            )

    def _encode(self, message: ProtocolMessage) -> bytes:
        try:
            return encode_message(message)
        except PluginWorkerProtocolError as error:
            self._fatal(
                "PLUGIN_WORKER_PROTOCOL_ERROR",
                "Parent protocol message exceeded its boundary",
                cause=error,
            )

    def _validate_result(
        self,
        result: PluginLifecycleResult,
        request_id: str,
        action: LifecycleAction,
    ) -> None:
        valid_correlation = (
            result.request_id == request_id and result.plugin_id == self._plugin_id
        )
        valid_success = (
            not result.success
            or (result.status == _SUCCESS_STATUS[action] and result.error == "")
        )
        valid_failure = result.success or result.status == "error"
        if not valid_correlation or not valid_success or not valid_failure:
            self._fatal(
                "PLUGIN_WORKER_PROTOCOL_ERROR",
                "Worker lifecycle result correlation or state was invalid",
            )

    def _fatal(
        self, code: str, message: str, cause: BaseException | None = None
    ) -> None:
        self._usable = False
        fault = self._transport_fault_value()
        confirmed = self._terminate_process()
        if fault is not None:
            error = PluginRuntimeError(*fault)
        elif self._process is not None and not confirmed:
            error = PluginRuntimeError(
                "PLUGIN_WORKER_TERMINATION_UNCONFIRMED",
                "Worker process termination could not be confirmed",
            )
        else:
            error = PluginRuntimeError(code, message)
        if cause is None:
            raise error
        raise error from cause

    def _terminate_process(self) -> bool:
        with self._termination_lock:
            with self._transport_fault_lock:
                self._termination_started.set()
                self._shutdown_response_eof_expected = False
                self._shutdown_response_eof_deferred = False
            process = self._process
            self._usable = False
            if process is None:
                return True
            stdin = process.stdin
            if stdin is not None:
                try:
                    stdin.close()
                except (OSError, ValueError):
                    pass

            self._wait_without_raising(process, self._timeouts.terminate)
            if process.poll() is None:
                contained = self._process_containment is not None
                tree_signalled = (
                    self._process_containment.terminate(force=False)
                    if contained
                    else False
                )
                terminate = getattr(process, "terminate", None)
                if not tree_signalled and callable(terminate):
                    try:
                        terminate()
                    except (OSError, ProcessLookupError):
                        pass
                self._wait_without_raising(process, self._timeouts.terminate)
            if process.poll() is None:
                contained = self._process_containment is not None
                tree_signalled = (
                    self._process_containment.terminate(force=True)
                    if contained
                    else False
                )
                kill = getattr(process, "kill", None)
                if not tree_signalled and callable(kill):
                    try:
                        kill()
                    except (OSError, ProcessLookupError):
                        pass
                self._wait_without_raising(process, self._timeouts.kill)

            direct_confirmed = process.poll() is not None
            tree_confirmed = direct_confirmed
            containment = self._process_containment
            if direct_confirmed and containment is not None:
                containment.terminate(force=True)
                tree_confirmed = containment.wait_empty(self._timeouts.kill)
            confirmed = direct_confirmed and tree_confirmed
            if confirmed:
                self._wait_without_raising(process, 0)
                for stream_name in ("stdout", "stderr"):
                    stream = getattr(process, stream_name, None)
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass
                readers_stopped = self._join_readers()
                if readers_stopped:
                    containment_closed = (
                        containment is None or containment.close()
                    )
                    if containment_closed:
                        self._cleanup_worker_temp()
                        self._cleanup_os_sandbox()
                        self._process = None
                        self._process_containment = None
                        self._stdout_thread = None
                        self._stderr_thread = None
                    else:
                        confirmed = False
            self._snapshot = PluginRuntimeSnapshot(
                self._plugin_id,
                self._snapshot.pid,
                self._load_spec.generation,
                confirmed,
            )
            return confirmed

    def _join_readers(self) -> bool:
        deadline = time.monotonic() + 0.2
        readers = (self._stdout_thread, self._stderr_thread)
        for thread in readers:
            if (
                thread is not None
                and thread is not threading.current_thread()
                and thread.is_alive()
            ):
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        return all(thread is None or not thread.is_alive() for thread in readers)

    @staticmethod
    def _wait_without_raising(process: subprocess.Popen[bytes], timeout: float) -> None:
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

    def _cleanup_worker_temp(self) -> None:
        worker_temp = self._worker_temp
        if worker_temp is not None:
            try:
                worker_temp.cleanup()
            except OSError:
                return
            self._worker_temp = None

    def _cleanup_container(self) -> None:
        container = self._container
        if container is None:
            return
        self._container = None
        try:
            container.close()
        except (OSError, WorkerContainerError):
            return

    def _cleanup_macos_sandbox(self) -> None:
        sandbox = self._macos_sandbox
        if sandbox is None:
            return
        self._macos_sandbox = None
        try:
            sandbox.close()
        except (OSError, WorkerMacOSSandboxError):
            return

    def _cleanup_os_sandbox(self) -> None:
        self._cleanup_container()
        self._cleanup_macos_sandbox()

    def _owned_writable_root(self) -> Path | None:
        if self._container is not None:
            return self._container.writable_root
        if self._macos_sandbox is not None:
            return self._macos_sandbox.writable_root
        return None


__all__ = [
    "PluginRuntimeError",
    "PluginRuntimeSnapshot",
    "PluginWorkerTimeouts",
    "SubprocessPluginRuntime",
]
