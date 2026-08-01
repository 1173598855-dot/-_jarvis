"""Parent-owned Popen transport for isolated Python Plugin Workers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable

from core.contracts.plugin_worker_protocol import (
    LifecycleAction,
    MAX_PLUGIN_WORKER_LINE_BYTES,
    PluginBrokerRequest,
    PluginLifecycleRequest,
    PluginLifecycleResult,
    PluginLoadSpec,
    PluginWorkerHello,
    PluginWorkerProtocolError,
    decode_message,
    encode_message,
    redact_protocol_error,
)
from core.kernel.plugin_broker import PluginBroker


MAX_CAPTURED_STDERR_BYTES = 8_192


@dataclass(frozen=True, slots=True)
class PluginWorkerTimeouts:
    """Parent-owned deadlines for the child transport."""

    handshake_seconds: float = 5.0
    load_seconds: float = 10.0
    activate_seconds: float = 30.0
    deactivate_seconds: float = 30.0
    cleanup_seconds: float = 30.0
    shutdown_seconds: float = 5.0
    terminate_seconds: float = 1.0
    kill_seconds: float = 1.0

    def __post_init__(self) -> None:
        for value in (
            self.handshake_seconds,
            self.load_seconds,
            self.activate_seconds,
            self.deactivate_seconds,
            self.cleanup_seconds,
            self.shutdown_seconds,
            self.terminate_seconds,
            self.kill_seconds,
        ):
            if value <= 0:
                raise ValueError("Plugin Worker timeouts must be positive")


class PluginRuntimeError(RuntimeError):
    """A bounded, stable parent-side Worker runtime failure."""

    def __init__(self, code: str, message: object = "") -> None:
        self.code = code
        self.message = redact_protocol_error(message)
        super().__init__(f"{code}: {self.message}" if self.message else code)


@dataclass(frozen=True, slots=True)
class PluginRuntimeSnapshot:
    plugin_id: str
    pid: int | None
    generation: int
    termination_confirmed: bool


@dataclass(frozen=True, slots=True)
class _TransportFault:
    code: str
    message: str


class _TransportFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class SubprocessPluginRuntime:
    """Own one Worker subprocess and mediate its complete protocol conversation."""

    def __init__(
        self,
        plugin_root: Path | str,
        load_spec: PluginLoadSpec,
        broker: PluginBroker,
        *,
        timeouts: PluginWorkerTimeouts | None = None,
        popen_factory: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        root = Path(plugin_root)
        if root.is_symlink() or not root.is_dir():
            raise PluginRuntimeError("PLUGIN_ROOT_INVALID", "Plugin root is invalid")
        if not isinstance(load_spec, PluginLoadSpec):
            raise TypeError("load_spec must be a PluginLoadSpec")
        if not isinstance(broker, PluginBroker):
            raise TypeError("broker must be a PluginBroker")

        self._plugin_root = root.resolve()
        self._plugin_id = self._plugin_root.name
        self._load_spec = load_spec
        self._broker = broker
        self._timeouts = timeouts or PluginWorkerTimeouts()
        self._popen_factory = popen_factory
        self._process: Any = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._messages: queue.Queue[object] = queue.Queue(maxsize=128)
        self._stderr = bytearray()
        self._stderr_lock = threading.Lock()
        self._invoke_lock = threading.Lock()
        self._request_count = 0
        self._worker_temp_dir: Path | None = None
        self._is_usable = False
        self._snapshot = PluginRuntimeSnapshot(
            plugin_id=self._plugin_id,
            pid=None,
            generation=load_spec.generation,
            termination_confirmed=False,
        )
        self._validate_entrypoint()

    @property
    def is_usable(self) -> bool:
        return self._is_usable

    @property
    def snapshot(self) -> PluginRuntimeSnapshot:
        return self._snapshot

    @property
    def stderr_text(self) -> str:
        with self._stderr_lock:
            return bytes(self._stderr).decode("utf-8", errors="replace")

    def process_is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> PluginRuntimeSnapshot:
        """Launch the trusted child entrypoint and require one valid hello."""
        if self._process is not None:
            if self._is_usable:
                return self._snapshot
            raise PluginRuntimeError("PLUGIN_WORKER_CRASHED", "Worker cannot be reused")

        self._worker_temp_dir = Path(tempfile.mkdtemp(prefix="jarvis-plugin-worker-"))
        worker_entrypoint = Path(__file__).resolve().parents[1] / "runtime" / "plugin_worker.py"
        arguments = [sys.executable, "-I", "-u", str(worker_entrypoint)]
        try:
            self._process = self._popen_factory(
                arguments,
                cwd=str(self._plugin_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self._sanitized_environment(),
                bufsize=0,
            )
        except Exception as exc:
            self._cleanup_worker_temp_dir()
            raise PluginRuntimeError("PLUGIN_WORKER_START_FAILED", exc) from exc

        self._start_readers()
        try:
            hello = self._next_message(self._timeouts.handshake_seconds)
        except _TransportFailure as failure:
            self._fatal(
                "PLUGIN_WORKER_HANDSHAKE_FAILED",
                failure.message,
            )
        if not isinstance(hello, PluginWorkerHello):
            self._fatal("PLUGIN_WORKER_HANDSHAKE_FAILED", "Worker did not send hello")
        self._is_usable = True
        self._snapshot = replace(self._snapshot, pid=hello.pid)
        return self._snapshot

    def invoke(self, action: LifecycleAction) -> PluginLifecycleResult:
        """Run one lifecycle action and synchronously broker child capability calls."""
        if not isinstance(action, LifecycleAction):
            raise TypeError("action must be a LifecycleAction")
        with self._invoke_lock:
            if not self._is_usable or not self.process_is_alive():
                raise PluginRuntimeError("PLUGIN_WORKER_CRASHED", "Worker is not usable")
            self._request_count += 1
            request_id = f"request-{self._request_count}"
            payload = self._load_spec.to_dict() if action is LifecycleAction.LOAD else {}
            request = PluginLifecycleRequest(
                request_id=request_id,
                plugin_id=self._plugin_id,
                action=action,
                payload=payload,
            )
            self._write_message(request)
            broker_session = None
            timeout = self._timeout_for(action)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    message = self._next_message(max(0.001, deadline - time.monotonic()))
                except _TransportFailure as failure:
                    if failure.code == "PLUGIN_WORKER_TIMEOUT":
                        self._fatal("PLUGIN_WORKER_TIMEOUT", failure.message)
                    self._fatal(failure.code, failure.message)
                if isinstance(message, PluginBrokerRequest):
                    if (
                        message.request_id != request_id
                        or message.plugin_id != self._plugin_id
                    ):
                        self._fatal(
                            "PLUGIN_WORKER_PROTOCOL_ERROR",
                            "Broker request correlation is invalid",
                        )
                    if broker_session is None:
                        broker_session = self._broker.begin_lifecycle(
                            self._plugin_id,
                            request_id,
                            self._load_spec.permissions,
                            self._load_spec.generation,
                        )
                    self._write_message(broker_session.handle(message))
                    continue
                if isinstance(message, PluginLifecycleResult):
                    if (
                        message.request_id != request_id
                        or message.plugin_id != self._plugin_id
                    ):
                        self._fatal(
                            "PLUGIN_WORKER_PROTOCOL_ERROR",
                            "Lifecycle result correlation is invalid",
                        )
                    return message
                self._fatal("PLUGIN_WORKER_PROTOCOL_ERROR", "Worker emitted an invalid message")

    def close(self) -> None:
        """Best-effort graceful shutdown followed by confirmed process reaping."""
        if self._process is None:
            self._cleanup_worker_temp_dir()
            return
        if self._is_usable and self.process_is_alive():
            try:
                self.invoke(LifecycleAction.SHUTDOWN)
            except PluginRuntimeError:
                pass
        self._is_usable = False
        self._terminate_and_reap()

    def _validate_entrypoint(self) -> None:
        candidate = self._plugin_root / self._load_spec.entry_point
        if Path(self._load_spec.entry_point).is_absolute():
            raise PluginRuntimeError("PLUGIN_ENTRYPOINT_INVALID", "Entrypoint is not relative")
        if candidate.is_symlink():
            raise PluginRuntimeError("PLUGIN_ENTRYPOINT_INVALID", "Entrypoint is a symbolic link")
        try:
            resolved = candidate.resolve()
            resolved.relative_to(self._plugin_root)
        except ValueError as exc:
            raise PluginRuntimeError("PLUGIN_ENTRYPOINT_INVALID", "Entrypoint escapes root") from exc
        if not resolved.is_file():
            raise PluginRuntimeError("PLUGIN_ENTRYPOINT_INVALID", "Entrypoint is invalid")

    def _sanitized_environment(self) -> dict[str, str]:
        environment: dict[str, str] = {}
        for name in ("PATH", "PATHEXT", "SystemRoot", "WINDIR", "ComSpec"):
            value = os.environ.get(name)
            if value is not None:
                environment[name] = value
        worker_temp = str(self._worker_temp_dir)
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONNOUSERSITE": "1",
                "TEMP": worker_temp,
                "TMP": worker_temp,
            }
        )
        return environment

    def _start_readers(self) -> None:
        if self._process.stdout is None or self._process.stderr is None:
            self._fatal("PLUGIN_WORKER_START_FAILED", "Worker pipes are unavailable")
        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            name=f"plugin-worker-stdout-{self._plugin_id}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name=f"plugin-worker-stderr-{self._plugin_id}",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        try:
            while True:
                line = self._process.stdout.readline(MAX_PLUGIN_WORKER_LINE_BYTES + 1)
                if not line:
                    self._put_message(_TransportFault("PLUGIN_WORKER_CRASHED", "Worker stdout closed"))
                    return
                if len(line) > MAX_PLUGIN_WORKER_LINE_BYTES:
                    self._put_message(
                        _TransportFault("PLUGIN_WORKER_OUTPUT_LIMIT", "Worker output exceeded limit")
                    )
                    return
                try:
                    self._put_message(decode_message(line))
                except PluginWorkerProtocolError:
                    self._put_message(
                        _TransportFault("PLUGIN_WORKER_PROTOCOL_ERROR", "Worker output is invalid")
                    )
                    return
        except Exception:
            self._put_message(_TransportFault("PLUGIN_WORKER_CRASHED", "Worker stdout failed"))

    def _read_stderr(self) -> None:
        try:
            while True:
                chunk = self._process.stderr.read(1_024)
                if not chunk:
                    return
                with self._stderr_lock:
                    remaining = MAX_CAPTURED_STDERR_BYTES - len(self._stderr)
                    if remaining > 0:
                        self._stderr.extend(chunk[:remaining])
        except Exception:
            return

    def _put_message(self, message: object) -> None:
        try:
            self._messages.put(message, timeout=0.1)
        except queue.Full:
            return

    def _next_message(self, timeout: float) -> object:
        if timeout <= 0:
            raise _TransportFailure("PLUGIN_WORKER_TIMEOUT", "Worker response timed out")
        try:
            message = self._messages.get(timeout=timeout)
        except queue.Empty as exc:
            if self._process is not None and self._process.poll() is not None:
                raise _TransportFailure("PLUGIN_WORKER_CRASHED", "Worker exited") from exc
            raise _TransportFailure("PLUGIN_WORKER_TIMEOUT", "Worker response timed out") from exc
        if isinstance(message, _TransportFault):
            raise _TransportFailure(message.code, message.message)
        return message

    def _write_message(self, message: object) -> None:
        if self._process is None or self._process.stdin is None:
            self._fatal("PLUGIN_WORKER_CRASHED", "Worker stdin is unavailable")
        try:
            self._process.stdin.write(encode_message(message))  # type: ignore[arg-type]
            self._process.stdin.flush()
        except Exception as exc:
            self._fatal("PLUGIN_WORKER_CRASHED", exc)

    def _timeout_for(self, action: LifecycleAction) -> float:
        return {
            LifecycleAction.LOAD: self._timeouts.load_seconds,
            LifecycleAction.ACTIVATE: self._timeouts.activate_seconds,
            LifecycleAction.DEACTIVATE: self._timeouts.deactivate_seconds,
            LifecycleAction.CLEANUP: self._timeouts.cleanup_seconds,
            LifecycleAction.SHUTDOWN: self._timeouts.shutdown_seconds,
        }[action]

    def _fatal(self, code: str, message: object) -> None:
        self._is_usable = False
        self._terminate_and_reap()
        raise PluginRuntimeError(code, message)

    def _terminate_and_reap(self) -> None:
        process = self._process
        if process is None:
            self._cleanup_worker_temp_dir()
            return
        self._close_stdin()
        if self._wait_for_exit(self._timeouts.shutdown_seconds):
            self._confirm_termination()
            return
        try:
            process.terminate()
        except Exception:
            pass
        if self._wait_for_exit(self._timeouts.terminate_seconds):
            self._confirm_termination()
            return
        try:
            process.kill()
        except Exception:
            pass
        if self._wait_for_exit(self._timeouts.kill_seconds):
            self._confirm_termination()

    def _close_stdin(self) -> None:
        try:
            if self._process is not None and self._process.stdin is not None:
                self._process.stdin.close()
        except Exception:
            pass

    def _wait_for_exit(self, timeout: float) -> bool:
        if self._process is None:
            return True
        if self._process.poll() is not None:
            return True
        try:
            self._process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, TimeoutError):
            return self._process.poll() is not None
        except Exception:
            return self._process.poll() is not None
        return self._process.poll() is not None

    def _confirm_termination(self) -> None:
        self._snapshot = replace(self._snapshot, termination_confirmed=True)
        self._close_output_streams()
        for reader in (self._reader_thread, self._stderr_thread):
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=0.2)
        self._cleanup_worker_temp_dir()

    def _close_output_streams(self) -> None:
        if self._process is None:
            return
        for stream in (self._process.stdout, self._process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    def _cleanup_worker_temp_dir(self) -> None:
        if self._worker_temp_dir is not None:
            shutil.rmtree(self._worker_temp_dir, ignore_errors=True)
            self._worker_temp_dir = None
