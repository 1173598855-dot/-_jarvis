"""Bounded, no-follow parent-directory durability for atomic replaces.

`os.replace()` makes a rename atomic but does not, on POSIX filesystems,
guarantee that the containing directory entry survives a crash. Callers that
already fsync the replacement file must also flush the parent directory to
make the new name durable.

This module owns that single primitive so every writable local repository
shares one contract:

* Windows and platforms without ``O_DIRECTORY`` have no portable directory
  descriptor to flush, so the call is a documented no-op.
* The directory is opened read-only, without following a final symlink, and
  the descriptor is always closed.
* Filesystems that legitimately cannot flush a directory (``EINVAL``,
  ``ENOSYS``, ``ENOTSUP``, ``EOPNOTSUPP``) are tolerated.
* Every other failure is raised so callers can fail closed instead of
  reporting durability they did not achieve.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EINVAL", None),
        getattr(errno, "ENOSYS", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
    )
    if value is not None
)


def supports_directory_fsync() -> bool:
    """Report whether this platform exposes a flushable directory descriptor."""
    return os.name != "nt" and hasattr(os, "O_DIRECTORY")


def fsync_directory(directory: str | Path) -> None:
    """Flush one directory entry, tolerating only unsupported-filesystem errnos.

    Raises:
        OSError: The directory could not be opened or flushed for any reason
            other than a filesystem that does not implement directory fsync.
    """
    if not supports_directory_fsync():
        return

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(directory, flags)
    except OSError as error:
        if error.errno in UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
            return
        raise
    try:
        os.fsync(descriptor)
    except OSError as error:
        if error.errno not in UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
            raise
    finally:
        os.close(descriptor)


__all__ = [
    "UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS",
    "fsync_directory",
    "supports_directory_fsync",
]
