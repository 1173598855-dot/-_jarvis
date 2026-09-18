"""
Terminal Executor ? ?? J.A.R.V.I.S. ??????????
??? Open Interpreter ???????

???
1. ?????/?????
2. ?????????
3. ???????
4. ??????
5. ??????
6. ??????

?????
- ?????????????
- ??????????
- ??????????
- ????????????
"""

import io
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TERMINAL_AUDIT_LIMIT = 1000
TERMINAL_PROCESS_READ_CHUNK_BYTES = 8 * 1024
TERMINAL_PROCESS_OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024


def _decode_process_output(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value or "")


def _read_bounded_process_stream(
    stream: object,
    limit: int,
    chunks: list[bytes],
    overflow: threading.Event,
) -> None:
    total = 0
    try:
        while not overflow.is_set():
            chunk = stream.read(TERMINAL_PROCESS_READ_CHUNK_BYTES)
            if not chunk:
                return
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            elif not isinstance(chunk, bytes):
                chunk = bytes(chunk)
            next_total = total + len(chunk)
            if next_total > limit:
                retained = limit - total
                if retained > 0:
                    chunks.append(chunk[:retained])
                overflow.set()
                return
            chunks.append(chunk)
            total = next_total
    except (OSError, TypeError, ValueError):
        return


def _bounded_process_communicate(
    process: object,
    *,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int,
) -> tuple[bytes | str, bytes | str, bool, bool]:
    """Collect both child streams without retaining output beyond raw limits."""
    stdout_stream = getattr(process, "stdout", None)
    stderr_stream = getattr(process, "stderr", None)
    stream_types = (io.RawIOBase, io.BufferedIOBase, io.BytesIO)

    # Test doubles from older suites expose communicate() but no real pipes.
    if not isinstance(stdout_stream, stream_types) or not isinstance(
        stderr_stream, stream_types
    ):
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return stdout, stderr, False, False
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except (OSError, AttributeError):
                pass
            stdout, stderr = process.communicate()
            return stdout, stderr, True, False

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    overflow = threading.Event()
    stdout_reader = threading.Thread(
        target=_read_bounded_process_stream,
        args=(stdout_stream, stdout_limit, stdout_chunks, overflow),
        daemon=True,
    )
    stderr_reader = threading.Thread(
        target=_read_bounded_process_stream,
        args=(stderr_stream, stderr_limit, stderr_chunks, overflow),
        daemon=True,
    )
    stdout_reader.start()
    stderr_reader.start()

    deadline = time.monotonic() + timeout
    timed_out = False
    killed = False

    def kill_once() -> None:
        nonlocal killed
        if killed:
            return
        killed = True
        try:
            process.kill()
        except (OSError, AttributeError):
            pass

    while True:
        if overflow.is_set():
            kill_once()
            break
        if process.poll() is not None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            kill_once()
            break
        try:
            process.wait(timeout=min(remaining, 0.05))
        except subprocess.TimeoutExpired:
            continue
        except (OSError, ValueError):
            break

    if killed:
        try:
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    stdout_reader.join(timeout=1.0)
    stderr_reader.join(timeout=1.0)
    for stream in (stdout_stream, stderr_stream):
        try:
            stream.close()
        except (OSError, AttributeError, ValueError):
            pass

    return (
        b"".join(stdout_chunks),
        b"".join(stderr_chunks),
        timed_out,
        overflow.is_set(),
    )


class CommandRisk(Enum):
    """??????"""
    SAFE = "safe"           # ???????
    MODERATE = "moderate"   # ???????
    DANGEROUS = "dangerous" # ??????????


@dataclass
class TerminalCommand:
    """??????"""
    id: str
    command: str
    args: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    risk_level: CommandRisk = CommandRisk.MODERATE


@dataclass
class TerminalResult:
    """??????"""
    command_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    success: bool
    risk_level: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:5000],  # ??????
            "stderr": self.stderr[:2000],
            "duration": round(self.duration, 3),
            "success": self.success,
            "risk_level": self.risk_level,
            "timestamp": self.timestamp,
        }


class TerminalExecutor:
    """
    ??????? ? ??? Open Interpreter ??

    ?????
    1. ???????????????????
    2. ????????????
    3. ????????????????
    4. ???????????
    5. ???????????
    """

    # ????? ? ???????
    SAFE_COMMANDS = {
        # ????
        "ls", "dir", "find", "which", "whereis", "type",
        # ????
        "cat", "head", "tail", "less", "more", "grep", "sed", "awk",
        "echo", "printf", "wc", "sort", "uniq", "tr",
        # ????
        "uname", "hostname", "whoami", "id", "date", "uptime",
        "ps", "top", "htop", "free", "df", "du", "lscpu",
        # ????
        "ping", "curl", "wget", "dig", "nslookup", "netstat", "ss",
        # Git
        "git",
        # Python
        "python", "python3", "pip", "pip3",
        # ??
        "env", "printenv", "pwd", "cd",
    }

    # ????? ? ????
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",           # ?????
        r"rm\s+-rf\s+~",           # ?? home
        r"rm\s+-rf\s+\*",          # ????
        r"mkfs",                    # ?????
        r"dd\s+if=",               # ????
        r">\s*/dev/",              # ????
        r"shred",                   # ????
        r"format\s+/",             # ???
        r":(){ :|:& };:",          # Fork bomb
        r"chmod\s+-R\s+777\s+/",  # ????
        r"sudo\s+rm",              # ????
        r"curl.*\|\s*(bash|sh)",  # ????????
        r"wget.*\|\s*(bash|sh)",  # ????????
        r"python.*\s+-c\s+.*rm",  # Python ??
        r"exec\s*\(.*rm",          # ??
        r"eval\s*\(.*rm",          # ??
    ]

    def __init__(
        self,
        allowed_commands: Optional[List[str]] = None,
        denied_commands: Optional[List[str]] = None,
        sandbox: bool = True,
        max_concurrency: int = 4,
        default_timeout: int = 30,
        max_output_size: int = 10000,
        *,
        allow_caller_context: bool = False,
        sandbox_dir: Optional[str | Path] = None,
    ):
        if type(sandbox) is not bool:
            raise ValueError("sandbox must be a boolean")
        if type(allow_caller_context) is not bool:
            raise ValueError("allow_caller_context must be a boolean")
        if sandbox is False and allow_caller_context is not True:
            raise ValueError(
                "sandbox=False requires explicit caller context authorization"
            )
        if sandbox is True and allow_caller_context:
            raise ValueError(
                "caller context authorization requires sandbox=False"
            )
        if sandbox_dir is not None and sandbox is not True:
            raise ValueError("sandbox_dir requires sandbox=True")
        self.allowed_commands = set(allowed_commands or self.SAFE_COMMANDS)
        self.denied_commands = set(denied_commands or [])
        self.sandbox = sandbox
        self.max_concurrency = max_concurrency
        self.default_timeout = default_timeout
        self.max_output_size = max_output_size
        if sandbox_dir is not None:
            external_sandbox = Path(sandbox_dir)
            if external_sandbox.is_symlink() or not external_sandbox.is_dir():
                raise ValueError("sandbox_dir must be a regular directory")
            self._sandbox_directory = None
            self.sandbox_dir = external_sandbox
        else:
            self._sandbox_directory = (
                tempfile.TemporaryDirectory(prefix="jarvis-terminal-")
                if sandbox
                else None
            )
            self.sandbox_dir = (
                Path(self._sandbox_directory.name)
                if self._sandbox_directory is not None
                else None
            )
        self._running_count = 0
        self._execution_condition = threading.Condition()
        self._closing = False
        self._audit_log: deque[Dict[str, Any]] = deque(maxlen=TERMINAL_AUDIT_LIMIT)
        self._audit_lock = threading.Lock()

    def close(self) -> None:
        """Release the executor-owned sandbox directory when the instance is retired."""
        with self._execution_condition:
            if self._sandbox_directory is None and self.sandbox_dir is None:
                return
            self._closing = True
            while self._running_count:
                self._execution_condition.wait()
            sandbox_directory = self._sandbox_directory
            if sandbox_directory is not None:
                sandbox_directory.cleanup()
            self._sandbox_directory = None
            self.sandbox_dir = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            # Interpreter shutdown can remove tempfile dependencies before this hook runs.
            pass

    def _sandbox_environment(self) -> Dict[str, str]:
        """Return the minimal process environment for an isolated local command."""
        if self.sandbox_dir is None:
            raise RuntimeError("Sandbox directory is unavailable")

        def read_environment(name: str) -> Optional[str]:
            for key, value in os.environ.items():
                if key.casefold() == name.casefold():
                    return value
            return None

        environment = {"PATH": read_environment("PATH") or os.defpath}
        for name in ("PATHEXT", "SystemRoot", "WINDIR", "ComSpec"):
            value = read_environment(name)
            if value:
                environment[name] = value
        if os.name == "nt":
            environment["TEMP"] = str(self.sandbox_dir)
            environment["TMP"] = str(self.sandbox_dir)
        else:
            environment["HOME"] = str(self.sandbox_dir)
            environment["TMPDIR"] = str(self.sandbox_dir)
        return environment

    def execute(self, cmd: TerminalCommand) -> TerminalResult:
        """
        ???????????

        ?????
        1. ?????
        2. ?????
        3. ??????
        4. ??????????
        5. ????
        6. ??????
        """
        if self.sandbox and self.sandbox_dir is None:
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr="Sandbox is closed",
                duration=0.0,
                success=False,
                risk_level=cmd.risk_level.value,
            )

        # ???? 1????
        full_command = f"{cmd.command} {' '.join(cmd.args)}"
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, full_command, re.IGNORECASE):
                logger.warning(f"??????: {full_command}")
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Security block: pattern '{pattern}'",
                    duration=0.0,
                    success=False,
                    risk_level=CommandRisk.DANGEROUS.value,
                )

        if self.sandbox and (cmd.cwd is not None or cmd.env):
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr="Sandbox policy rejects caller working-directory or environment overrides",
                duration=0.0,
                success=False,
                risk_level=cmd.risk_level.value,
            )

        # validate working directory
        cwd = self.sandbox_dir if self.sandbox else Path(cmd.cwd or os.getcwd())
        if not os.path.isdir(cwd):
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr=f"Working directory not found: {cwd}",
                duration=0.0,
                success=False,
                risk_level=cmd.risk_level.value,
            )

        # ???? 2????
        base_cmd = cmd.command.split()[0] if cmd.command else ""
        if base_cmd in self.denied_commands:
            logger.warning(f"???????: {base_cmd}")
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr=f"Denied command blocked: '{base_cmd}'",
                duration=0.0,
                success=False,
                risk_level=CommandRisk.DANGEROUS.value,
            )
        if base_cmd not in self.allowed_commands:
            logger.warning(f"???????: {base_cmd}")
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr=f"Unauthorized command blocked: '{base_cmd}' not in allowlist",
                duration=0.0,
                success=False,
                risk_level=CommandRisk.DANGEROUS.value,
            )

        # ????
        with self._execution_condition:
            if self.sandbox and (self._closing or self.sandbox_dir is None):
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout="",
                    stderr="Sandbox is closed",
                    duration=0.0,
                    success=False,
                    risk_level=cmd.risk_level.value,
                )
            if self._running_count >= self.max_concurrency:
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout="",
                    stderr=f"??????? {self._running_count}/{self.max_concurrency} ??????",
                    duration=0.0,
                    success=False,
                    risk_level=CommandRisk.MODERATE.value,
                )
            self._running_count += 1
        try:
            result = self._run_command(cmd)
        finally:
            with self._execution_condition:
                self._running_count -= 1
                if self._running_count == 0:
                    self._execution_condition.notify_all()

        # ????
        with self._audit_lock:
            self._audit_log.append({
                "command_id": cmd.id,
                "command": full_command[:200],
                "risk_level": cmd.risk_level.value,
                "success": result.success,
                "timestamp": datetime.now().isoformat(),
            })

        return result

    def _run_command(self, cmd: TerminalCommand) -> TerminalResult:
        start_time = time.perf_counter()
        try:
            if os.name == "nt" and cmd.command.lower() == "echo" and not cmd.env:
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=0,
                    stdout=f"{' '.join(cmd.args)}\n",
                    stderr="",
                    duration=time.perf_counter() - start_time,
                    success=True,
                    risk_level=cmd.risk_level.value,
                )

            full_cmd = [cmd.command] + cmd.args

            # ????
            cwd = self.sandbox_dir if self.sandbox else Path(cmd.cwd or os.getcwd())
            if not os.path.isdir(cwd):
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Working directory not found: {cwd}",
                    duration=0.0,
                    success=False,
                    risk_level=cmd.risk_level.value,
                )

            # ????
            env = self._sandbox_environment() if self.sandbox else {**os.environ, **cmd.env}

            # ??
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                shell=False,
            )

            stdout, stderr, timed_out, output_limited = _bounded_process_communicate(
                process,
                timeout=cmd.timeout,
                stdout_limit=TERMINAL_PROCESS_OUTPUT_LIMIT_BYTES,
                stderr_limit=TERMINAL_PROCESS_OUTPUT_LIMIT_BYTES,
            )
            stdout_text = _decode_process_output(stdout)
            stderr_text = _decode_process_output(stderr)
            if output_limited:
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout=stdout_text[: self.max_output_size],
                    stderr="Command output exceeded the safety limit",
                    duration=time.perf_counter() - start_time,
                    success=False,
                    risk_level=cmd.risk_level.value,
                )
            if timed_out:
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout=stdout_text[: self.max_output_size],
                    stderr=f"???{cmd.timeout}s?",
                    duration=cmd.timeout,
                    success=False,
                    risk_level=cmd.risk_level.value,
                )

            # ????
            stdout_text = stdout_text[: self.max_output_size]
            stderr_text = stderr_text[: self.max_output_size // 2]

            duration = time.perf_counter() - start_time

            return TerminalResult(
                command_id=cmd.id,
                exit_code=process.returncode,
                stdout=stdout_text,
                stderr=stderr_text,
                duration=duration,
                success=process.returncode == 0,
                risk_level=cmd.risk_level.value,
            )

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration=0.0,
                success=False,
                risk_level=cmd.risk_level.value,
            )

    def execute_shell(self, shell_command: str, timeout: Optional[int] = None) -> TerminalResult:
        """
        ?? Shell ????????

        Args:
            shell_command: ?? shell ?????
            timeout: ???????

        Returns:
            TerminalResult
        """
        if timeout is None:
            timeout = self.default_timeout

        # ????
        try:
            parts = shlex.split(shell_command)
        except (TypeError, ValueError) as error:
            return TerminalResult(
                command_id="shell",
                exit_code=-1,
                stdout="",
                stderr=str(error),
                duration=0.0,
                success=False,
                risk_level=CommandRisk.DANGEROUS.value,
            )
        if not parts:
            return TerminalResult(
                command_id="shell",
                exit_code=-1,
                stdout="",
                stderr="???",
                duration=0.0,
                success=False,
                risk_level=CommandRisk.DANGEROUS.value,
            )

        cmd = TerminalCommand(
            id=f"shell-{int(time.time() * 1000)}",
            command=parts[0],
            args=parts[1:],
            timeout=timeout,
            risk_level=self._assess_risk(parts[0]),
        )

        return self.execute(cmd)

    def _assess_risk(self, command: str) -> CommandRisk:
        """????????"""
        base_cmd = command.split()[0] if command else ""

        # ??????
        dangerous = {"rm", "dd", "mkfs", "shred", "format", "chmod"}
        if base_cmd in dangerous:
            return CommandRisk.DANGEROUS

        # ??????
        moderate = {"mv", "cp", "touch", "mkdir", "pip", "npm"}
        if base_cmd in moderate:
            return CommandRisk.MODERATE

        return CommandRisk.SAFE

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """??????"""
        if type(limit) is not int or limit < 0:
            raise ValueError("Audit log limit must be a non-negative integer")
        if limit == 0:
            return []
        with self._audit_lock:
            return [entry.copy() for entry in list(self._audit_log)[-limit:]]

    def clear_audit_log(self):
        """??????"""
        with self._audit_lock:
            self._audit_log.clear()


# ============================================================
# CLI ??
# ============================================================

def main():
    """?????"""

    if len(sys.argv) < 2:
        print("??: python terminal_executor.py <command> [args...]")
        print("\n??:")
        print("  python terminal_executor.py ls -la")
        print("  python terminal_executor.py pwd")
        print("  python terminal_executor.py python3 --version")
        sys.exit(1)

    executor = TerminalExecutor()
    shell_command = " ".join(sys.argv[1:])

    print(f"?? ??: {shell_command}")
    print("-" * 60)

    result = executor.execute_shell(shell_command)

    if result.success:
        print(result.stdout)
    else:
        print(f"? ?? (exit {result.exit_code}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)

    print("-" * 60)
    print(f"??  ??: {result.duration:.2f}s")
    print(f"??  ????: {result.risk_level}")

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
