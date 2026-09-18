"""OS-level network isolation for trusted child Workers."""

from __future__ import annotations

import errno
import os
import sys
from typing import Any

CLONE_NEWNET = 0x40000000
CLONE_NEWUSER = 0x10000000
WORKER_NETWORK_ISOLATION = ("network_namespace",)


class WorkerNetworkIsolationError(RuntimeError):
    """The declared Worker network boundary could not be enforced."""


def _write_namespace_control(path: str, payload: bytes) -> None:
    flags = (
        os.O_WRONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
        try:
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise WorkerNetworkIsolationError(
                    "Worker user namespace identity mapping was incomplete"
                )
        finally:
            try:
                os.close(descriptor)
            except OSError as error:
                raise WorkerNetworkIsolationError(
                    "cannot close Worker user namespace mapping descriptor"
                ) from error
    except WorkerNetworkIsolationError:
        raise
    except OSError as error:
        raise WorkerNetworkIsolationError(
            "cannot map the Worker user namespace identity"
        ) from error


def _map_current_identity(uid: int, gid: int) -> None:
    _write_namespace_control("/proc/self/setgroups", b"deny\n")
    _write_namespace_control("/proc/self/uid_map", f"{uid} {uid} 1\n".encode("ascii"))
    _write_namespace_control("/proc/self/gid_map", f"{gid} {gid} 1\n".encode("ascii"))


def isolate_worker_network(
    *,
    ctypes_module: Any | None = None,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """Enter a private Linux network namespace before loading Worker code."""
    platform = sys.platform if platform_name is None else platform_name
    if not platform.startswith("linux"):
        # Windows AppContainer and macOS sandbox profiles require separate
        # parent-owned launch integration and are deliberately out of scope.
        return ()

    if ctypes_module is None:
        try:
            import ctypes as ctypes_module  # noqa: PLC0415
        except ImportError as error:
            raise WorkerNetworkIsolationError(
                "cannot load the Worker network isolation interface"
            ) from error

    try:
        libc = ctypes_module.CDLL(None, use_errno=True)
        unshare = libc.unshare
        unshare.argtypes = (ctypes_module.c_int,)
        unshare.restype = ctypes_module.c_int
    except (AttributeError, OSError, TypeError) as error:
        raise WorkerNetworkIsolationError(
            "cannot load the Worker network isolation syscall"
        ) from error

    try:
        result = unshare(CLONE_NEWNET)
        error_number = ctypes_module.get_errno()
    except (OSError, ValueError) as error:
        raise WorkerNetworkIsolationError(
            "cannot enter the Worker network namespace"
        ) from error
    if result == 0:
        return WORKER_NETWORK_ISOLATION
    if error_number != errno.EPERM:
        raise WorkerNetworkIsolationError(
            f"cannot enter the Worker network namespace: errno {error_number}"
        )

    uid = os.geteuid()
    gid = os.getegid()
    try:
        result = unshare(CLONE_NEWUSER | CLONE_NEWNET)
        error_number = ctypes_module.get_errno()
    except (OSError, ValueError) as error:
        raise WorkerNetworkIsolationError(
            "cannot enter the Worker user and network namespaces"
        ) from error
    if result != 0:
        raise WorkerNetworkIsolationError(
            "cannot enter the Worker user and network namespaces: "
            f"errno {error_number}"
        )
    _map_current_identity(uid, gid)
    return WORKER_NETWORK_ISOLATION


__all__ = [
    "CLONE_NEWNET",
    "CLONE_NEWUSER",
    "WORKER_NETWORK_ISOLATION",
    "WorkerNetworkIsolationError",
    "isolate_worker_network",
]
