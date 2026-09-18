"""Fixed OS-level resource budgets for trusted child Workers."""

from __future__ import annotations

import os
from typing import Any

# Each budget below is scoped to this single process. RLIMIT_NPROC is
# deliberately excluded: on Linux it counts every process and thread for the
# real UID system-wide, so it cannot express a per-Worker ceiling and would
# fail closed against unrelated host load. Descendant process count is
# limited by the parent-owned Windows Job Object instead.
WORKER_RESOURCE_BUDGETS = {
    "core_bytes": 0,
    "file_bytes": 64 * 1024 * 1024,
    "open_files": 256,
}

_LIMIT_ATTRIBUTES = (
    ("core_bytes", "RLIMIT_CORE"),
    ("file_bytes", "RLIMIT_FSIZE"),
    ("open_files", "RLIMIT_NOFILE"),
)


class WorkerResourceLimitError(RuntimeError):
    """A declared Worker resource budget could not be enforced."""


def _lowered_bound(current: int, target: int, infinity: int) -> int:
    if current == infinity or current < 0:
        return target
    return min(current, target)


def apply_worker_resource_limits(
    *,
    resource_module: Any | None = None,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """Lower this process to the declared budgets and report what applied."""
    platform = os.name if platform_name is None else platform_name
    if platform != "posix":
        # Windows budgets are owned by the parent Job Object, which a child
        # cannot tighten for its own tree.
        return ()

    if resource_module is None:
        try:
            import resource as resource_module  # noqa: PLC0415
        except ImportError:
            return ()

    infinity = getattr(resource_module, "RLIM_INFINITY", -1)
    applied: list[str] = []
    for name, attribute in _LIMIT_ATTRIBUTES:
        key = getattr(resource_module, attribute, None)
        if key is None:
            continue
        target = WORKER_RESOURCE_BUDGETS[name]
        try:
            soft, hard = resource_module.getrlimit(key)
        except (OSError, ValueError) as error:
            raise WorkerResourceLimitError(
                f"cannot read the {name} Worker resource budget"
            ) from error
        bound = min(
            _lowered_bound(soft, target, infinity),
            _lowered_bound(hard, target, infinity),
        )
        try:
            resource_module.setrlimit(key, (bound, bound))
        except (OSError, ValueError) as error:
            raise WorkerResourceLimitError(
                f"cannot enforce the {name} Worker resource budget"
            ) from error
        applied.append(name)
    return tuple(applied)


__all__ = [
    "WORKER_RESOURCE_BUDGETS",
    "WorkerResourceLimitError",
    "apply_worker_resource_limits",
]
