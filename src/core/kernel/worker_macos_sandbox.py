"""Parent-owned macOS Seatbelt sandbox for one Plugin Worker."""

from __future__ import annotations

import posixpath
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

from core.kernel.worker_staging import (
    WORKER_STAGE_ENTRY_BUDGET,
    WorkerStagingError,
    stage_worker_tree,
)
from core.kernel.worker_windows_isolation import default_runtime_read_paths

MACOS_SANDBOX_LAUNCHER = "sandbox-exec"
MACOS_STAGE_ENTRY_BUDGET = WORKER_STAGE_ENTRY_BUDGET
WORKER_MACOS_SANDBOX = (
    "sandbox-exec",
    "seatbelt",
    "staged-readonly-code",
    "writable-root",
)


class WorkerMacOSSandboxError(RuntimeError):
    """The parent-owned macOS Worker sandbox could not be established."""


def _seatbelt_path(path: str | Path) -> str:
    """Return one absolute, control-free path suitable for a Seatbelt literal."""
    try:
        raw = str(path)
    except (TypeError, ValueError) as error:
        raise WorkerMacOSSandboxError("macOS sandbox path was not string-like") from error
    if not raw or "\x00" in raw or not raw.startswith("/"):
        raise WorkerMacOSSandboxError("macOS sandbox paths must be absolute")
    if ".." in raw.split("/"):
        raise WorkerMacOSSandboxError("macOS sandbox paths cannot contain traversal")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise WorkerMacOSSandboxError("macOS sandbox paths cannot contain control characters")
    normalized = posixpath.normpath(raw)
    if normalized == "/":
        raise WorkerMacOSSandboxError("macOS sandbox paths cannot be the filesystem root")
    return normalized


def _seatbelt_literal(path: str | Path) -> str:
    normalized = _seatbelt_path(path)
    escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def macos_sandbox_profile(
    read_paths: tuple[str | Path, ...],
    writable_root: str | Path,
    executable_path: str | Path | None = None,
) -> str:
    """Build a default-deny profile with bounded reads and one write root."""
    if not isinstance(read_paths, tuple):
        raise WorkerMacOSSandboxError("macOS sandbox read paths must be a tuple")
    unique_reads: list[str] = []
    seen: set[str] = set()
    for path in read_paths:
        normalized = _seatbelt_path(path)
        if normalized not in seen:
            seen.add(normalized)
            unique_reads.append(normalized)
    runtime_paths = tuple(unique_reads)
    writable = _seatbelt_path(writable_root)
    if writable not in seen:
        unique_reads.append(writable)
    lines = ["(version 1)", "(deny default)"]
    lines.extend(
        f"(allow file-read* (subpath {_seatbelt_literal(path)}))"
        for path in unique_reads
    )
    lines.extend(
        f"(allow file-map-executable (subpath {_seatbelt_literal(path)}))"
        for path in runtime_paths
    )
    lines.append(f"(allow file-write* (subpath {_seatbelt_literal(writable)}))")
    if executable_path is not None:
        lines.append(
            f"(allow process-exec (literal {_seatbelt_literal(executable_path)}))"
        )
    lines.extend(
        (
            "(allow process-fork)",
            "(allow signal (target self))",
            "(allow sysctl-read)",
        )
    )
    return "\n".join(lines) + "\n"


def _remove_sandbox_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


class MacOSSandbox:
    """One parent-owned macOS staging root and Seatbelt policy."""

    def __init__(
        self,
        *,
        root: Path,
        code_root: Path,
        writable_root: Path,
        launcher: str,
        profile: str,
    ) -> None:
        self.root = root
        self.code_root = code_root
        self.writable_root = writable_root
        self.launcher = launcher
        self.profile = profile
        self.labels = WORKER_MACOS_SANDBOX
        self._closed = False

    @classmethod
    def create(
        cls,
        *,
        launcher_lookup: Callable[[str], str | None] | None = None,
        temporary_directory: Callable[..., str] | None = None,
        runtime_read_paths: tuple[str | Path, ...] | None = None,
    ) -> "MacOSSandbox":
        make_temporary = tempfile.mkdtemp if temporary_directory is None else temporary_directory
        try:
            root = Path(make_temporary(prefix="jarvis-worker-macos-"))
            code_root = root / "code"
            writable_root = root / "tmp"
            code_root.mkdir(parents=True, exist_ok=False)
            writable_root.mkdir(parents=True, exist_ok=False)
            lookup = shutil.which if launcher_lookup is None else launcher_lookup
            launcher = lookup(MACOS_SANDBOX_LAUNCHER)
            if not launcher:
                raise WorkerMacOSSandboxError(
                    "macOS sandbox-exec launcher is unavailable"
                )
            paths = (
                default_runtime_read_paths()
                if runtime_read_paths is None
                else runtime_read_paths
            )
            profile = macos_sandbox_profile(
                tuple(paths) + (code_root,),
                writable_root,
                executable_path=str(Path(sys.executable).resolve()),
            )
            return cls(
                root=root,
                code_root=code_root,
                writable_root=writable_root,
                launcher=str(launcher),
                profile=profile,
            )
        except WorkerMacOSSandboxError:
            if "root" in locals():
                _remove_sandbox_root(root)
            raise
        except (OSError, WorkerStagingError) as error:
            if "root" in locals():
                _remove_sandbox_root(root)
            raise WorkerMacOSSandboxError(
                "cannot create the macOS Worker sandbox"
            ) from error

    def stage(self, source: Path, name: str) -> Path:
        if self._closed:
            raise WorkerMacOSSandboxError("the macOS Worker sandbox is closed")
        if not name or name in {".", ".."} or Path(name).parts != (name,):
            raise WorkerMacOSSandboxError("macOS Worker stage name is invalid")
        destination = self.code_root / name
        if destination.exists():
            raise WorkerMacOSSandboxError(
                f"macOS Worker stage target already exists: {name}"
            )
        try:
            stage_worker_tree(source, destination)
        except WorkerStagingError as error:
            raise WorkerMacOSSandboxError(str(error)) from error
        return destination

    def spawn(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        popen: Callable[..., Any] | None = None,
        **launch_keywords: Any,
    ) -> Any:
        if self._closed:
            raise WorkerMacOSSandboxError("the macOS Worker sandbox is closed")
        factory = subprocess.Popen if popen is None else popen
        return factory(
            [self.launcher, "-p", self.profile, *list(arguments)],
            cwd=str(cwd),
            env=dict(environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            close_fds=True,
            **launch_keywords,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _remove_sandbox_root(self.root)

    def close_spawn_handle(self) -> None:
        """Compatibility hook matching the Windows container interface."""
        return None


__all__ = [
    "MACOS_SANDBOX_LAUNCHER",
    "MACOS_STAGE_ENTRY_BUDGET",
    "MacOSSandbox",
    "WORKER_MACOS_SANDBOX",
    "WorkerMacOSSandboxError",
    "macos_sandbox_profile",
]
