from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess


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
        completed = subprocess.run(
            command,
            cwd=self._repository_root,
            shell=False,
            check=True,
            capture_output=True,
            timeout=10,
            env=environment,
        )
        output = completed.stdout
        if isinstance(output, str):
            return output.encode("utf-8", errors="surrogateescape")
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
