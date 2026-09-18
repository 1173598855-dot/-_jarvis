"""Bounded, link-free staging for parent-owned Worker sandboxes."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable

WORKER_STAGE_ENTRY_BUDGET = 8_192


class WorkerStagingError(RuntimeError):
    """A Worker source tree cannot be staged safely."""


def stage_worker_tree(
    source: Path,
    destination: Path,
    *,
    entry_budget: int = WORKER_STAGE_ENTRY_BUDGET,
    copy_tree: Callable[..., Any] | None = None,
) -> int:
    """Copy one bounded, link-free tree into a parent-owned staging root."""
    if not isinstance(entry_budget, int) or isinstance(entry_budget, bool) or entry_budget <= 0:
        raise WorkerStagingError("Worker stage budget must be a positive integer")
    entries = _counted_tree_entries(source, entry_budget)
    copy = shutil.copytree if copy_tree is None else copy_tree
    try:
        copy(
            source,
            destination,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    except (OSError, shutil.Error) as error:
        raise WorkerStagingError(
            f"cannot stage the Worker tree from {source}"
        ) from error
    return entries


def _counted_tree_entries(source: Path, entry_budget: int) -> int:
    """Count tree entries, failing closed on links, budget overflow or errors."""
    try:
        if not source.is_dir():
            raise WorkerStagingError(
                f"Worker stage source is not a directory: {source}"
            )
    except OSError as error:
        raise WorkerStagingError(
            f"cannot inspect the Worker stage source {source}"
        ) from error
    seen = 0
    pending = [source]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as scan:
                for entry in scan:
                    seen += 1
                    if seen > entry_budget:
                        raise WorkerStagingError(
                            "Worker stage source exceeded its entry budget"
                        )
                    try:
                        if entry.is_symlink():
                            raise WorkerStagingError(
                                "Worker stage source contains a link"
                            )
                        if entry.name == "__pycache__" and entry.is_dir():
                            continue
                        if entry.is_dir():
                            pending.append(Path(entry.path))
                    except OSError as error:
                        raise WorkerStagingError(
                            "cannot inspect a Worker stage entry"
                        ) from error
        except OSError as error:
            raise WorkerStagingError(
                f"cannot scan the Worker stage source {current}"
            ) from error
    return seen


__all__ = [
    "WORKER_STAGE_ENTRY_BUDGET",
    "WorkerStagingError",
    "stage_worker_tree",
]
