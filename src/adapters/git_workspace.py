from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ENVIRONMENT_KEYS = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
)
_MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024
_GIT_READ_CHUNK_BYTES = 64 * 1024
_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    head: str
    branch: str
    dirty_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.head, str) or not _COMMIT.fullmatch(self.head):
            raise ValueError("head must be a 40-character lowercase Git commit")
        if not isinstance(self.branch, str) or not self.branch.strip():
            raise ValueError("branch must be a non-empty string")
        if not isinstance(self.dirty_paths, tuple) or not all(
            isinstance(path, str) and path for path in self.dirty_paths
        ):
            raise ValueError("dirty_paths must be a tuple of non-empty strings")
        object.__setattr__(self, "dirty_paths", tuple(sorted(set(self.dirty_paths))))


class GitWorkspaceInspector:
    def __init__(self, repository_root: Path) -> None:
        self._repository_root = Path(repository_root).resolve()

    def snapshot(self) -> WorkspaceSnapshot:
        head = self._run(("git", "rev-parse", "HEAD")).decode("ascii").strip()
        branch = (
            self._run(("git", "branch", "--show-current"))
            .decode("utf-8", errors="surrogateescape")
            .strip()
            or "HEAD"
        )
        status = self._run(("git", "status", "--porcelain=v1", "-z"))
        return WorkspaceSnapshot(
            head=head,
            branch=branch,
            dirty_paths=self._parse_dirty_paths(status),
        )

    def _run(self, command: tuple[str, ...]) -> bytes:
        environment = {
            key: os.environ[key]
            for key in _ENVIRONMENT_KEYS
            if key in os.environ
        }
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        process = subprocess.Popen(
            command,
            cwd=self._repository_root,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        overflow = threading.Event()

        def read_stream(stream: object, chunks: list[bytes]) -> None:
            total = 0
            try:
                while not overflow.is_set():
                    chunk = stream.read(_GIT_READ_CHUNK_BYTES)
                    if not chunk:
                        return
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8", errors="surrogateescape")
                    elif not isinstance(chunk, bytes):
                        chunk = bytes(chunk)
                    next_total = total + len(chunk)
                    if next_total > _MAX_GIT_OUTPUT_BYTES:
                        retained = _MAX_GIT_OUTPUT_BYTES - total
                        if retained > 0:
                            chunks.append(chunk[:retained])
                        overflow.set()
                        return
                    chunks.append(chunk)
                    total = next_total
            except (OSError, TypeError, ValueError):
                return

        stdout_reader = threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout_chunks),
            daemon=True,
        )
        stderr_reader = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr_chunks),
            daemon=True,
        )
        stdout_reader.start()
        stderr_reader.start()

        deadline = time.monotonic() + _GIT_TIMEOUT_SECONDS
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
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except (OSError, AttributeError, ValueError):
                pass

        output = b"".join(stdout_chunks)
        error_output = b"".join(stderr_chunks)
        if overflow.is_set():
            raise ValueError(
                f"git output exceeds {_MAX_GIT_OUTPUT_BYTES} bytes"
            )
        if timed_out:
            raise subprocess.TimeoutExpired(command, _GIT_TIMEOUT_SECONDS)
        returncode = process.returncode
        if returncode:
            raise subprocess.CalledProcessError(
                returncode,
                command,
                output=output,
                stderr=error_output,
            )
        return output

    @staticmethod
    def _parse_dirty_paths(output: bytes) -> tuple[str, ...]:
        records = output.decode("utf-8", errors="surrogateescape").split("\0")
        paths: list[str] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 4 or record[2] != " ":
                raise ValueError("git status returned an invalid porcelain record")
            status = record[:2]
            paths.append(record[3:])
            if "R" in status or "C" in status:
                if index >= len(records) or not records[index]:
                    raise ValueError("git status returned an incomplete rename record")
                paths.append(records[index])
                index += 1
        return tuple(sorted(set(paths)))
