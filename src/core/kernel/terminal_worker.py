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
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .terminal_executor import CommandRisk, TerminalCommand, TerminalExecutor, TerminalResult
from .terminal_policy import TerminalPolicyError, validate_terminal_operation


WORKER_COMMANDS = frozenset({"echo", "pwd", "whoami", "hostname", "date"})
WORKER_MODULE_ROOT = Path(__file__).resolve().parents[2]
WORKER_FLAG = "--worker"
WORKER_RESPONSE_LIMIT = 64 * 1024


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


def _worker_environment(sandbox_dir: Path) -> dict[str, str]:
    """Build an environment that excludes service secrets and user overrides."""
    def inherited(name: str) -> str | None:
        for key, value in os.environ.items():
            if key.casefold() == name.casefold():
                return value
        return None

    environment: dict[str, str] = {
        "PATH": inherited("PATH") or os.defpath,
        "PYTHONPATH": str(WORKER_MODULE_ROOT),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
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
        environment["TMPDIR"] = str(sandbox_dir)

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


def _worker_main() -> int:
    """Read one request from stdin, execute it, and emit one JSON response."""
    try:
        _drop_worker_privileges()
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise TerminalPolicyError("Worker request must be an object")
        command, args, timeout = validate_terminal_operation(
            request.get("command"), request.get("args"), request.get("timeout")
        )
        if command not in WORKER_COMMANDS:
            raise TerminalPolicyError("Worker command is not available")

        executor = TerminalExecutor(
            allowed_commands=set(WORKER_COMMANDS),
            sandbox=True,
            default_timeout=timeout,
        )
        try:
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
        finally:
            executor.close()
        sys.stdout.write(json.dumps(asdict(result), ensure_ascii=False))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0
    except Exception as error:
        result = _result_failure(
            str(locals().get("request", {}).get("command_id", "worker")),
            str(error),
        )
        sys.stdout.write(json.dumps(asdict(result), ensure_ascii=False))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0


class TerminalWorker:
    """Small process-isolated adapter implementing the terminal executor API."""

    def __init__(self, max_output_size: int = 10000):
        self.max_output_size = max_output_size
        self._sandbox_directory = tempfile.TemporaryDirectory(
            prefix="jarvis-terminal-worker-"
        )
        self.sandbox_dir = Path(self._sandbox_directory.name)
        self._closed = False
        self._audit_log: list[dict[str, Any]] = []

    def close(self) -> None:
        if not self._closed:
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
            data = json.loads(payload)
            if not isinstance(data, Mapping):
                raise ValueError("Worker response must be an object")
            return TerminalResult(
                command_id=str(data.get("command_id", cmd.id)),
                exit_code=int(data.get("exit_code", -1)),
                stdout=str(data.get("stdout", ""))[: self.max_output_size],
                stderr=str(data.get("stderr", ""))[: self.max_output_size // 2],
                duration=float(data.get("duration", 0.0)),
                success=bool(data.get("success", False)),
                risk_level=str(data.get("risk_level", cmd.risk_level.value)),
                timestamp=str(data.get("timestamp", "")),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            return self._failure(cmd, f"Invalid worker response: {error}")

    def execute(self, cmd: TerminalCommand) -> TerminalResult:
        if self._closed or self.sandbox_dir is None:
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
        process: subprocess.Popen[str] | None = None
        started = time.perf_counter()
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "core.kernel.terminal_worker", WORKER_FLAG],
                cwd=WORKER_MODULE_ROOT,
                env=_worker_environment(self.sandbox_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                start_new_session=(os.name != "nt"),
            )
            stdout, _stderr = process.communicate(
                json.dumps(request, ensure_ascii=False),
                timeout=timeout + 2,
            )
            if process.returncode != 0:
                return self._record(
                    cmd,
                    self._failure(cmd, f"Worker exited with status {process.returncode}"),
                )
            result = self._decode_result(cmd, (stdout or "").strip())
            if result.duration == 0.0:
                result.duration = time.perf_counter() - started
            return self._record(cmd, result)
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                process.communicate()
            return self._record(cmd, self._failure(cmd, f"Worker timed out after {timeout}s"))
        except (OSError, ValueError) as error:
            return self._record(cmd, self._failure(cmd, f"Worker launch failed: {error}"))

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_log[-limit:]

    def clear_audit_log(self) -> None:
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
