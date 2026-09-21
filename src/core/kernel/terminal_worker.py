"""Process boundary for the fixed, read-only terminal capability.

The HTTP services use :class:`TerminalWorker` by default.  Every request is
handled by a short-lived child process with a minimal environment and an
executor-owned temporary directory.  The child accepts the same fixed
operation contract as the HTTP policy; it never receives a shell command,
working-directory override, or caller environment.
"""

from __future__ import annotations

import getpass
import json
import math
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .process_containment import (
    ProcessTreeContainment,
    process_group_popen_kwargs,
)
from .terminal_executor import (
    TERMINAL_AUDIT_LIMIT,
    CommandRisk,
    TerminalCommand,
    TerminalExecutor,
    TerminalResult,
    _bounded_process_communicate,
    _decode_process_output,
)
from .terminal_policy import TerminalPolicyError, validate_terminal_operation
from .worker_filesystem_isolation import isolate_worker_filesystem
from .worker_macos_sandbox import MacOSSandbox, WorkerMacOSSandboxError
from .worker_network_isolation import isolate_worker_network
from .worker_resource_limits import apply_worker_resource_limits
from .worker_windows_container import WindowsWorkerContainer, WorkerContainerError

WORKER_COMMANDS = frozenset({"echo", "pwd", "whoami", "hostname", "date"})
WORKER_MODULE_ROOT = Path(__file__).resolve().parents[2]
WORKER_FLAG = "--worker"
WORKER_REQUEST_LIMIT = 32 * 1024
WORKER_RESPONSE_LIMIT = 64 * 1024
WORKER_TREE_RELEASE_TIMEOUT = 5.0
_REAL_SUBPROCESS_POPEN = subprocess.Popen
_WORKER_SOURCE_STAGE = "src"
_WINDOWS_PLATFORM = "nt"
_WORKER_RESPONSE_FIELDS = frozenset({
    "command_id",
    "exit_code",
    "stdout",
    "stderr",
    "duration",
    "success",
    "risk_level",
    "timestamp",
})


def _unique_response_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Worker response contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_response_constant(_value: str) -> None:
    raise ValueError("Worker response contains a non-finite JSON number")


def _result_failure(command_id: str, message: str, risk: str = "dangerous") -> TerminalResult:
    return TerminalResult(
        command_id=command_id,
        exit_code=-1,
        stdout="",
        stderr=message,
        duration=0.0,
        success=False,
        risk_level=risk,
    )


def _worker_environment(
    sandbox_dir: Path,
    module_root: Path = WORKER_MODULE_ROOT,
) -> dict[str, str]:
    """Build an environment that excludes service secrets and user overrides."""
    def inherited(name: str) -> str | None:
        for key, value in os.environ.items():
            if key.casefold() == name.casefold():
                return value
        return None

    environment: dict[str, str] = {
        "PATH": inherited("PATH") or os.defpath,
        "PYTHONPATH": str(module_root),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(sandbox_dir),
    }
    for name in ("PATHEXT", "SystemRoot", "WINDIR", "ComSpec"):
        value = inherited(name)
        if value:
            environment[name] = value
    if os.name == "nt":
        environment["TEMP"] = str(sandbox_dir)
        environment["TMP"] = str(sandbox_dir)
    else:
        environment["HOME"] = str(sandbox_dir)

    # Identity changes are opt-in and must be configured by the service owner.
    for name in ("JARVIS_TERMINAL_WORKER_UID", "JARVIS_TERMINAL_WORKER_GID"):
        value = inherited(name)
        if value:
            environment[name] = value
    return environment


def _drop_worker_privileges() -> None:
    """Drop to explicitly configured POSIX ids before creating the executor."""
    if os.name != "posix":
        return

    def configured_id(name: str) -> int | None:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return None
        try:
            value = int(raw, 10)
        except ValueError as error:
            raise RuntimeError(f"Invalid worker identity: {name}") from error
        if value < 0:
            raise RuntimeError(f"Invalid worker identity: {name}")
        return value

    gid = configured_id("JARVIS_TERMINAL_WORKER_GID")
    uid = configured_id("JARVIS_TERMINAL_WORKER_UID")
    if gid is not None:
        if os.geteuid() != 0 and gid != os.getegid():
            raise RuntimeError("Worker GID change requires a privileged parent")
        os.setgid(gid)
    if uid is not None:
        if os.geteuid() != 0 and uid != os.geteuid():
            raise RuntimeError("Worker UID change requires a privileged parent")
        os.setuid(uid)


def _run_read_only_operation(
    command: str,
    args: list[str],
    sandbox_dir: Path,
) -> str | None:
    """Resolve platform-dependent diagnostics without invoking a shell."""
    if command == "echo":
        return " ".join(args) + "\n"
    if command == "pwd":
        return f"{sandbox_dir}\n"
    if command == "whoami":
        try:
            username = getpass.getuser()
        except (KeyError, OSError):
            username = "unknown"
        return f"{username}\n"
    if command == "hostname":
        return f"{socket.gethostname()}\n"
    if command == "date":
        return f"{datetime.now().astimezone().strftime('%a %b %d %H:%M:%S %Z %Y')}\n"
    return None


def _read_worker_request() -> object:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(WORKER_REQUEST_LIMIT + 1)
    if isinstance(raw, str):
        try:
            encoded = raw.encode("utf-8")
        except UnicodeEncodeError as error:
            raise TerminalPolicyError("Worker request must be UTF-8") from error
        if len(encoded) > WORKER_REQUEST_LIMIT:
            raise TerminalPolicyError("Worker request exceeds the input limit")
        text = raw
    elif isinstance(raw, (bytes, bytearray)):
        if len(raw) > WORKER_REQUEST_LIMIT:
            raise TerminalPolicyError("Worker request exceeds the input limit")
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as error:
            raise TerminalPolicyError("Worker request must be UTF-8") from error
    else:
        raise TerminalPolicyError("Worker request stream is invalid")
    return json.loads(text)


def _worker_sandbox_path() -> Path:
    """Return the parent-owned temporary root supplied to this Worker."""
    variables = ("TMPDIR", "TEMP") if os.name == "nt" else ("TMPDIR",)
    for variable in variables:
        raw_path = os.environ.get(variable, "").strip()
        if raw_path:
            return Path(raw_path)
    raise RuntimeError(f"Worker {variables[0]} is unavailable")


def _worker_main() -> int:
    """Read one request from stdin, execute it, and emit one JSON response."""
    request: object = None
    executor: TerminalExecutor | None = None
    previous_tempdir = tempfile.tempdir
    try:
        apply_worker_resource_limits()
        isolate_worker_network()
        worker_sandbox = _worker_sandbox_path()
        isolate_worker_filesystem(worker_sandbox, root_writable=True)
        tempfile.tempdir = str(worker_sandbox)
        _drop_worker_privileges()
        executor = TerminalExecutor(
            allowed_commands=set(WORKER_COMMANDS),
            sandbox=True,
            sandbox_dir=worker_sandbox,
            default_timeout=30,
        )
        request = _read_worker_request()
        if not isinstance(request, dict):
            raise TerminalPolicyError("Worker request must be an object")
        command, args, timeout = validate_terminal_operation(
            request.get("command"), request.get("args"), request.get("timeout")
        )
        if command not in WORKER_COMMANDS:
            raise TerminalPolicyError("Worker command is not available")

        command_id = str(request.get("command_id", "worker"))
        risk_level = CommandRisk(str(request.get("risk_level", "safe")))
        started = time.perf_counter()
        output = _run_read_only_operation(command, args, executor.sandbox_dir)
        if output is not None:
            result = TerminalResult(
                command_id=command_id,
                exit_code=0,
                stdout=output,
                stderr="",
                duration=time.perf_counter() - started,
                success=True,
                risk_level=risk_level.value,
            )
        else:
            result = executor.execute(
                TerminalCommand(
                    id=command_id,
                    command=command,
                    args=args,
                    timeout=timeout,
                    risk_level=risk_level,
                )
            )
        sys.stdout.write(json.dumps(asdict(result), ensure_ascii=False))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0
    except Exception as error:
        command_id = (
            str(request.get("command_id", "worker"))
            if isinstance(request, dict)
            else "worker"
        )
        result = _result_failure(
            command_id,
            str(error),
        )
        sys.stdout.write(json.dumps(asdict(result), ensure_ascii=False))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0
    finally:
        if executor is not None:
            executor.close()
        tempfile.tempdir = previous_tempdir


class TerminalWorker:
    """Small process-isolated adapter implementing the terminal executor API."""

    def __init__(
        self,
        max_output_size: int = 10000,
        *,
        os_isolation: bool | None = None,
        container_factory: Callable[[], WindowsWorkerContainer] | None = None,
        macos_sandbox_factory: Callable[[], MacOSSandbox] | None = None,
    ):
        self.max_output_size = max_output_size
        self._sandbox_directory = tempfile.TemporaryDirectory(
            prefix="jarvis-terminal-worker-"
        )
        self.sandbox_dir = Path(self._sandbox_directory.name)
        self._os_isolation = os_isolation
        self._container_factory = container_factory
        self._macos_sandbox_factory = macos_sandbox_factory
        self._os_sandbox: WindowsWorkerContainer | MacOSSandbox | None = None
        self._os_sandbox_platform: str | None = None
        self._staged_source: Path | None = None
        self._os_sandbox_lock = threading.Lock()
        self._closed = False
        self._closing = False
        self._execution_condition = threading.Condition()
        self._running_count = 0
        self._owned_containments: set[ProcessTreeContainment] = set()
        self._audit_log: deque[dict[str, Any]] = deque(maxlen=TERMINAL_AUDIT_LIMIT)
        self._audit_lock = threading.Lock()

    def close(self) -> None:
        with self._execution_condition:
            if self._closed:
                return
            self._closing = True
            while self._running_count:
                self._execution_condition.wait()
            if self._closed:
                return
            if not self._release_owned_containments():
                raise RuntimeError("Worker process tree could not be released")
            if not self._cleanup_os_sandbox():
                raise RuntimeError("Worker OS sandbox could not be released")
            self._sandbox_directory.cleanup()
            self._closed = True
            self.sandbox_dir = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _assess_risk(self, command: str) -> CommandRisk:
        return CommandRisk.SAFE if command in WORKER_COMMANDS else CommandRisk.DANGEROUS

    @property
    def default_timeout(self) -> int:
        return 30

    def _failure(self, cmd: TerminalCommand, message: str) -> TerminalResult:
        return _result_failure(cmd.id, message, cmd.risk_level.value)

    def _record(self, cmd: TerminalCommand, result: TerminalResult) -> TerminalResult:
        with self._audit_lock:
            self._audit_log.append({
                "command_id": cmd.id,
                "command": cmd.command,
                "risk_level": result.risk_level,
                "success": result.success,
                "timestamp": result.timestamp,
            })
        return result

    def _decode_result(self, cmd: TerminalCommand, payload: str) -> TerminalResult:
        if len(payload.encode("utf-8")) > WORKER_RESPONSE_LIMIT:
            return self._failure(cmd, "Worker response exceeds the safety limit")
        try:
            data = json.loads(
                payload,
                object_pairs_hook=_unique_response_object,
                parse_constant=_reject_response_constant,
            )
            if type(data) is not dict:
                raise ValueError("Worker response must be an exact object")
            if set(data) != _WORKER_RESPONSE_FIELDS:
                raise ValueError("Worker response fields are invalid")

            for field_name in (
                "command_id",
                "stdout",
                "stderr",
                "risk_level",
                "timestamp",
            ):
                if type(data[field_name]) is not str:
                    raise ValueError(f"Worker response {field_name} must be a string")
            if type(data["exit_code"]) is not int:
                raise ValueError("Worker response exit_code must be an integer")
            if type(data["success"]) is not bool:
                raise ValueError("Worker response success must be a boolean")

            duration = data["duration"]
            if type(duration) not in (int, float) or duration < 0:
                raise ValueError("Worker response duration must be finite and non-negative")
            try:
                normalized_duration = float(duration)
            except OverflowError as error:
                raise ValueError(
                    "Worker response duration must be finite and non-negative"
                ) from error
            if not math.isfinite(normalized_duration):
                raise ValueError("Worker response duration must be finite and non-negative")

            if data["command_id"] != cmd.id:
                raise ValueError("Worker response command correlation is invalid")
            if data["risk_level"] != cmd.risk_level.value:
                raise ValueError("Worker response risk correlation is invalid")
            if data["success"] != (data["exit_code"] == 0):
                raise ValueError("Worker response status is inconsistent")
            if not data["timestamp"]:
                raise ValueError("Worker response timestamp is invalid")
            try:
                datetime.fromisoformat(data["timestamp"])
            except ValueError as error:
                raise ValueError("Worker response timestamp is invalid") from error

            return TerminalResult(
                command_id=data["command_id"],
                exit_code=data["exit_code"],
                stdout=data["stdout"][: self.max_output_size],
                stderr=data["stderr"][: self.max_output_size // 2],
                duration=normalized_duration,
                success=data["success"],
                risk_level=data["risk_level"],
                timestamp=data["timestamp"],
            )
        except (TypeError, ValueError, json.JSONDecodeError, RecursionError) as error:
            return self._failure(cmd, f"Invalid worker response: {error}")

    def _should_use_os_isolation(self) -> bool:
        if self._os_isolation is not None:
            return bool(self._os_isolation)
        if (
            self._container_factory is not None
            or self._macos_sandbox_factory is not None
        ):
            return True
        return (
            subprocess.Popen is _REAL_SUBPROCESS_POPEN
            and (os.name == _WINDOWS_PLATFORM or sys.platform == "darwin")
        )

    def _ensure_os_sandbox(
        self,
    ) -> tuple[WindowsWorkerContainer | MacOSSandbox, Path]:
        with self._os_sandbox_lock:
            if self._os_sandbox is not None:
                if self._staged_source is None or self._os_sandbox_platform is None:
                    raise RuntimeError("Worker OS sandbox setup is incomplete")
                return self._os_sandbox, self._staged_source

            if self._macos_sandbox_factory is not None or (
                sys.platform == "darwin" and self._container_factory is None
            ):
                platform_name = "macos"
                factory: Callable[[], WindowsWorkerContainer | MacOSSandbox] = (
                    MacOSSandbox.create
                    if self._macos_sandbox_factory is None
                    else self._macos_sandbox_factory
                )
            elif self._container_factory is not None or os.name == _WINDOWS_PLATFORM:
                platform_name = "windows"
                factory = (
                    WindowsWorkerContainer.create
                    if self._container_factory is None
                    else self._container_factory
                )
            else:
                raise RuntimeError(
                    "Worker OS isolation is unavailable on this platform"
                )

            sandbox = factory()
            self._os_sandbox = sandbox
            self._os_sandbox_platform = platform_name
            try:
                staged_source = sandbox.stage(
                    WORKER_MODULE_ROOT, _WORKER_SOURCE_STAGE
                )
            except BaseException:
                self._cleanup_os_sandbox_unlocked()
                raise
            self._staged_source = staged_source
            return sandbox, self._staged_source

    def _spawn_isolated(self) -> tuple[subprocess.Popen[Any], bool]:
        sandbox, staged_source = self._ensure_os_sandbox()
        if self._os_sandbox_platform == "windows":
            interpreter = str(getattr(sandbox, "interpreter"))
            suspended = True
        elif self._os_sandbox_platform == "macos":
            interpreter = sys.executable
            suspended = False
        else:
            raise RuntimeError("Worker OS isolation platform is invalid")
        process = sandbox.spawn(
            [
                interpreter,
                "-S",
                "-u",
                "-m",
                "core.kernel.terminal_worker",
                WORKER_FLAG,
            ],
            cwd=staged_source,
            environment=_worker_environment(sandbox.writable_root, staged_source),
            **process_group_popen_kwargs(),
        )
        return process, suspended

    def execute(self, cmd: TerminalCommand) -> TerminalResult:
        with self._execution_condition:
            if self._closed or self._closing or self.sandbox_dir is None:
                return self._record(cmd, self._failure(cmd, "Terminal worker is closed"))
        if cmd.cwd is not None or cmd.env:
            return self._record(
                cmd,
                self._failure(
                    cmd,
                    "Worker policy rejects caller working-directory or environment overrides",
                ),
            )
        try:
            command, args, timeout = validate_terminal_operation(
                cmd.command, list(cmd.args), cmd.timeout
            )
            if command not in WORKER_COMMANDS:
                raise TerminalPolicyError("Worker command is not available")
        except (TerminalPolicyError, TypeError, ValueError) as error:
            return self._record(cmd, self._failure(cmd, str(error)))

        request = {
            "command_id": cmd.id,
            "command": command,
            "args": args,
            "timeout": timeout,
            "risk_level": cmd.risk_level.value,
        }
        try:
            request_bytes = json.dumps(request, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            return self._record(cmd, self._failure(cmd, f"Worker request encoding failed: {error}"))
        if len(request_bytes) > WORKER_REQUEST_LIMIT:
            return self._record(
                cmd,
                self._failure(cmd, "Worker request exceeds the safety limit"),
            )
        with self._execution_condition:
            if self._closed or self._closing or self.sandbox_dir is None:
                return self._record(cmd, self._failure(cmd, "Terminal worker is closed"))
            self._running_count += 1
        try:
            return self._execute_reserved(cmd, request_bytes, timeout)
        finally:
            with self._execution_condition:
                self._running_count -= 1
                if self._running_count == 0:
                    self._execution_condition.notify_all()

    def _execute_reserved(
        self,
        cmd: TerminalCommand,
        request_bytes: bytes,
        timeout: int,
    ) -> TerminalResult:
        process: subprocess.Popen[Any] | None = None
        containment: ProcessTreeContainment | None = None
        isolated_launch = False
        cleanup_isolated_sandbox = False
        setup_complete = False
        process_reaped = False
        started = time.perf_counter()
        try:
            isolated_launch = self._should_use_os_isolation()
            if isolated_launch:
                process, suspended = self._spawn_isolated()
            else:
                suspended = False
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-S",
                        "-m",
                        "core.kernel.terminal_worker",
                        WORKER_FLAG,
                    ],
                    cwd=WORKER_MODULE_ROOT,
                    env=_worker_environment(self.sandbox_dir),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    **process_group_popen_kwargs(),
                )
            try:
                containment = ProcessTreeContainment.attach(process)
            except Exception as error:
                cleanup_isolated_sandbox = isolated_launch
                process.kill()
                process.wait()
                process_reaped = True
                return self._record(
                    cmd,
                    self._failure(cmd, f"Worker containment failed: {error}"),
                )
            if containment is not None:
                self._remember_containment(containment)
            if suspended:
                resume = getattr(process, "resume", None)
                if not callable(resume):
                    raise RuntimeError("contained Worker cannot resume")
                resume()
            setup_complete = True
            worker_stdin = getattr(process, "stdin", None)
            if worker_stdin is not None:
                worker_stdin.write(request_bytes)
                worker_stdin.flush()
                worker_stdin.close()
            stdout, _stderr, timed_out, output_limited = _bounded_process_communicate(
                process,
                timeout=timeout + 2,
                stdout_limit=WORKER_RESPONSE_LIMIT,
                stderr_limit=8 * 1024,
            )
            if timed_out:
                return self._record(
                    cmd,
                    self._failure(cmd, f"Worker timed out after {timeout}s"),
                )
            if output_limited:
                return self._record(
                    cmd,
                    self._failure(cmd, "Worker response exceeds the safety limit"),
                )
            if process.returncode != 0:
                return self._record(
                    cmd,
                    self._failure(cmd, f"Worker exited with status {process.returncode}"),
                )
            result = self._decode_result(cmd, _decode_process_output(stdout).strip())
            if result.duration == 0.0:
                result.duration = time.perf_counter() - started
            if not self._release_containment(containment):
                return self._record(
                    cmd,
                    self._failure(cmd, "Worker process tree could not be released"),
                )
            self._forget_containment(containment)
            containment = None
            return self._record(cmd, result)
        except (
            OSError,
            ValueError,
            RuntimeError,
            WorkerContainerError,
            WorkerMacOSSandboxError,
        ) as error:
            cleanup_isolated_sandbox = isolated_launch and not setup_complete
            return self._record(cmd, self._failure(cmd, f"Worker launch failed: {error}"))
        finally:
            # Any path that did not already confirm release owns the cleanup, so
            # a killed or leaked descendant cannot outlive the parent request.
            if containment is not None and self._release_containment(containment):
                self._forget_containment(containment)
                containment = None
                process_reaped = True
            if (
                cleanup_isolated_sandbox
                and containment is None
                and (process is None or process_reaped)
            ):
                self._cleanup_os_sandbox()
            if process is not None:
                try:
                    process.wait(timeout=0)
                except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
                    pass
                close_spawn_handle = getattr(process, "close_spawn_handle", None)
                if callable(close_spawn_handle):
                    try:
                        close_spawn_handle()
                    except (OSError, RuntimeError, ValueError, AttributeError):
                        pass

    def _remember_containment(self, containment: ProcessTreeContainment) -> None:
        with self._execution_condition:
            self._owned_containments.add(containment)

    def _forget_containment(self, containment: ProcessTreeContainment) -> None:
        with self._execution_condition:
            self._owned_containments.discard(containment)

    def _release_owned_containments(self) -> bool:
        with self._execution_condition:
            containments = list(self._owned_containments)
        all_released = True
        for containment in containments:
            if self._release_containment(containment):
                self._forget_containment(containment)
            else:
                all_released = False
        return all_released

    def _cleanup_os_sandbox_unlocked(self) -> bool:
        sandbox = self._os_sandbox
        if sandbox is None:
            return True
        try:
            sandbox.close()
        except (OSError, WorkerContainerError, WorkerMacOSSandboxError):
            return False
        self._os_sandbox = None
        self._os_sandbox_platform = None
        self._staged_source = None
        return True

    def _cleanup_os_sandbox(self) -> bool:
        with self._os_sandbox_lock:
            return self._cleanup_os_sandbox_unlocked()

    def _release_containment(
        self,
        containment: ProcessTreeContainment | None,
    ) -> bool:
        """Terminate, confirm empty, and release one owned Worker tree."""
        if containment is None:
            return True
        containment.terminate(force=True)
        if not containment.wait_empty(WORKER_TREE_RELEASE_TIMEOUT):
            return False
        return containment.close()

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or limit < 0:
            raise ValueError("Audit log limit must be a non-negative integer")
        if limit == 0:
            return []
        with self._audit_lock:
            return [entry.copy() for entry in list(self._audit_log)[-limit:]]

    def clear_audit_log(self) -> None:
        with self._audit_lock:
            self._audit_log.clear()

    def execute_shell(self, shell_command: str, timeout: int = 30) -> TerminalResult:
        try:
            parts = shlex.split(shell_command)
        except ValueError as error:
            return _result_failure("shell", str(error))
        if not parts:
            return _result_failure("shell", "Empty command")
        return self.execute(
            TerminalCommand(
                id=f"worker-shell-{int(time.time() * 1000)}",
                command=parts[0],
                args=parts[1:],
                timeout=timeout,
                risk_level=self._assess_risk(parts[0]),
            )
        )


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
    raise SystemExit(_worker_main())
