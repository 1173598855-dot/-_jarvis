"""OS-level filesystem isolation for trusted child Workers."""

from __future__ import annotations

import os
import platform as platform_module
import stat
import sys
import sysconfig
from pathlib import Path
from typing import Any, Callable

LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_TYPE_PATH_BENEATH = 1
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

LANDLOCK_ACCESS_FS_ABI_1 = (
    (1 << 13) - 1
)
LANDLOCK_ACCESS_FS_ABI_2 = LANDLOCK_ACCESS_FS_ABI_1 | LANDLOCK_ACCESS_FS_REFER
LANDLOCK_ACCESS_FS_ABI_3 = LANDLOCK_ACCESS_FS_ABI_2 | LANDLOCK_ACCESS_FS_TRUNCATE

LANDLOCK_SYSCALL_NUMBERS = {
    "aarch64": (444, 445, 446),
    "amd64": (444, 445, 446),
    "arm64": (444, 445, 446),
    "i386": (444, 445, 446),
    "ppc64le": (444, 445, 446),
    "riscv64": (444, 445, 446),
    "s390x": (444, 445, 446),
    "x86_64": (444, 445, 446),
}

PR_SET_NO_NEW_PRIVS = 38
WORKER_FILESYSTEM_ISOLATION = ("landlock",)

_READ_ACCESS = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR
_TEMP_ACCESS = (
    _READ_ACCESS
    | LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_TRUNCATE
)


class WorkerFilesystemIsolationError(RuntimeError):
    """The declared Worker filesystem boundary could not be enforced."""


class _LandlockRulesetAttr:
    def __init__(self, ctypes_module: Any, handled_access_fs: int) -> None:
        class RulesetAttr(ctypes_module.Structure):
            _fields_ = [("handled_access_fs", ctypes_module.c_ulonglong)]

        self.value = RulesetAttr(handled_access_fs)


class _LandlockPathBeneathAttr:
    def __init__(
        self, ctypes_module: Any, allowed_access: int, parent_fd: int
    ) -> None:
        class PathBeneathAttr(ctypes_module.Structure):
            _fields_ = [
                ("allowed_access", ctypes_module.c_ulonglong),
                ("parent_fd", ctypes_module.c_int),
            ]

        self.value = PathBeneathAttr(allowed_access, parent_fd)


class _LandlockApi:
    def __init__(
        self,
        *,
        ctypes_module: Any | None = None,
        machine_name: str | None = None,
    ) -> None:
        if ctypes_module is None:
            try:
                import ctypes as ctypes_module  # noqa: PLC0415
            except ImportError as error:
                raise WorkerFilesystemIsolationError(
                    "cannot load the Worker filesystem isolation interface"
                ) from error
        machine = (
            platform_module.machine().lower()
            if machine_name is None
            else machine_name.lower()
        )
        numbers = LANDLOCK_SYSCALL_NUMBERS.get(machine)
        if numbers is None:
            raise WorkerFilesystemIsolationError(
                "cannot identify the Worker filesystem isolation syscall"
            )
        self._ctypes = ctypes_module
        try:
            libc = ctypes_module.CDLL(None, use_errno=True)
            syscall = libc.syscall
            syscall.restype = ctypes_module.c_long
            prctl = libc.prctl
            prctl.argtypes = (
                ctypes_module.c_int,
                ctypes_module.c_ulong,
                ctypes_module.c_ulong,
                ctypes_module.c_ulong,
                ctypes_module.c_ulong,
            )
            prctl.restype = ctypes_module.c_int
        except (AttributeError, OSError, TypeError) as error:
            raise WorkerFilesystemIsolationError(
                "cannot load the Worker filesystem isolation syscall"
            ) from error
        self._syscall = syscall
        self._prctl = prctl
        (
            self._create_ruleset_number,
            self._add_rule_number,
            self._restrict_self_number,
        ) = numbers

    def _syscall_checked(self, number: int, *arguments: Any) -> int:
        try:
            result = int(self._syscall(number, *arguments))
            error_number = int(self._ctypes.get_errno())
        except (OSError, TypeError, ValueError) as error:
            raise WorkerFilesystemIsolationError(
                "Worker filesystem isolation syscall failed"
            ) from error
        if result < 0:
            raise WorkerFilesystemIsolationError(
                f"Worker filesystem isolation syscall failed: errno {error_number}"
            )
        return result

    def query_abi(self) -> int:
        version = self._syscall_checked(
            self._create_ruleset_number,
            self._ctypes.c_void_p(0),
            self._ctypes.c_size_t(0),
            self._ctypes.c_uint(LANDLOCK_CREATE_RULESET_VERSION),
        )
        if version < 1:
            raise WorkerFilesystemIsolationError(
                "Worker filesystem isolation is not supported"
            )
        return version

    def create_ruleset(self, handled_access_fs: int) -> int:
        attr = _LandlockRulesetAttr(
            self._ctypes, handled_access_fs
        ).value
        return self._syscall_checked(
            self._create_ruleset_number,
            self._ctypes.byref(attr),
            self._ctypes.c_size_t(self._ctypes.sizeof(attr)),
            self._ctypes.c_uint(0),
        )

    def add_rule(
        self, ruleset_fd: int, allowed_access: int, parent_fd: int
    ) -> None:
        attr = _LandlockPathBeneathAttr(
            self._ctypes, allowed_access, parent_fd
        ).value
        self._syscall_checked(
            self._add_rule_number,
            self._ctypes.c_int(ruleset_fd),
            self._ctypes.c_uint(LANDLOCK_RULE_TYPE_PATH_BENEATH),
            self._ctypes.byref(attr),
            self._ctypes.c_uint(0),
        )

    def restrict_self(self, ruleset_fd: int) -> None:
        try:
            result = int(self._prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))
            error_number = int(self._ctypes.get_errno())
        except (OSError, TypeError, ValueError) as error:
            raise WorkerFilesystemIsolationError(
                "cannot enable Worker no-new-privileges"
            ) from error
        if result != 0:
            raise WorkerFilesystemIsolationError(
                f"cannot enable Worker no-new-privileges: errno {error_number}"
            )
        self._syscall_checked(
            self._restrict_self_number,
            self._ctypes.c_int(ruleset_fd),
            self._ctypes.c_uint(0),
        )

    @staticmethod
    def close(fd: int) -> None:
        try:
            os.close(fd)
        except OSError as error:
            raise WorkerFilesystemIsolationError(
                "cannot close Worker filesystem isolation descriptor"
            ) from error


def _directory_path(path: str | Path) -> Path:
    candidate = Path(path)
    try:
        absolute = candidate.absolute()
        raw = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        if (
            not stat.S_ISDIR(raw.st_mode)
            or absolute != resolved
            or not resolved.is_dir()
        ):
            raise WorkerFilesystemIsolationError(
                "Worker filesystem isolation path must be a real directory"
            )
        return resolved
    except WorkerFilesystemIsolationError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise WorkerFilesystemIsolationError(
            "Worker filesystem isolation path is unavailable"
        ) from error


def _default_allowed_paths(
    worker_root: Path,
    *,
    root_writable: bool,
) -> tuple[tuple[Path, bool], ...]:
    candidates: list[Path] = [
        worker_root,
        Path(__file__).resolve().parents[2],
    ]
    writable: list[Path] = []
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        value = sysconfig.get_path(key)
        if value:
            candidates.append(Path(value))
    for key in ("LIBDIR", "LIBPL"):
        value = sysconfig.get_config_var(key)
        if value:
            candidates.append(Path(value))
    for value in sys.path:
        if not value:
            continue
        path = Path(value)
        if path.is_file():
            path = path.parent
        candidates.append(path)
    for variable in ("TMP", "TEMP", "TMPDIR"):
        value = os.environ.get(variable)
        if value:
            path = Path(value)
            candidates.append(path)
            writable.append(path)

    unique: dict[str, tuple[Path, bool]] = {}
    for candidate in candidates:
        try:
            resolved = _directory_path(candidate)
        except WorkerFilesystemIsolationError:
            if candidate in writable:
                raise
            continue
        key = str(resolved)
        writable_path = candidate in writable or any(
            candidate_path.absolute() == resolved for candidate_path in writable
        )
        unique[key] = (
            resolved,
            root_writable if resolved == worker_root else writable_path,
        )
    return tuple(unique.values())


def _handled_access_for_abi(abi: int) -> int:
    if abi < 1:
        raise WorkerFilesystemIsolationError(
            f"unsupported Worker filesystem isolation ABI: {abi}"
        )
    if abi >= 3:
        return LANDLOCK_ACCESS_FS_ABI_3
    if abi >= 2:
        return LANDLOCK_ACCESS_FS_ABI_2
    return LANDLOCK_ACCESS_FS_ABI_1


def isolate_worker_filesystem(
    plugin_root: str | Path,
    *,
    ctypes_module: Any | None = None,
    machine_name: str | None = None,
    platform_name: str | None = None,
    api_factory: Callable[[], Any] | None = None,
    allowed_paths: tuple[tuple[str | Path, bool], ...] | None = None,
    root_writable: bool = False,
) -> tuple[str, ...]:
    """Restrict a Linux Worker to trusted read and explicitly writable roots."""
    platform_name = sys.platform if platform_name is None else platform_name
    if not platform_name.startswith("linux"):
        return ()

    root = _directory_path(plugin_root)
    api = api_factory() if api_factory is not None else _LandlockApi(
        ctypes_module=ctypes_module, machine_name=machine_name
    )
    abi = int(api.query_abi())
    handled_access = _handled_access_for_abi(abi)
    ruleset_fd = int(api.create_ruleset(handled_access))
    directory_fds: list[int] = []
    try:
        paths = (
            tuple((Path(path), writable) for path, writable in allowed_paths)
            if allowed_paths is not None
            else _default_allowed_paths(root, root_writable=root_writable)
        )
        if allowed_paths is not None and root_writable:
            paths = tuple(
                (path, True if _directory_path(path) == root else writable)
                for path, writable in paths
            )
        if not any(_directory_path(path) == root for path, _ in paths):
            raise WorkerFilesystemIsolationError(
                "Worker filesystem isolation omitted the plugin root"
            )
        open_flags = (
            getattr(os, "O_PATH", 0)
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        if not getattr(os, "O_PATH", 0):
            raise WorkerFilesystemIsolationError(
                "Worker filesystem isolation requires O_PATH"
            )
        for raw_path, writable in paths:
            path = _directory_path(raw_path)
            expected = path.stat()
            descriptor = os.open(path, open_flags)
            directory_fds.append(descriptor)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_dev != expected.st_dev
                or opened.st_ino != expected.st_ino
            ):
                raise WorkerFilesystemIsolationError(
                    "Worker filesystem isolation path changed during setup"
                )
            allowed = _TEMP_ACCESS if writable else _READ_ACCESS
            api.add_rule(ruleset_fd, allowed & handled_access, descriptor)
        api.restrict_self(ruleset_fd)
    finally:
        close_error: WorkerFilesystemIsolationError | None = None
        for descriptor in reversed(directory_fds):
            try:
                api.close(descriptor)
            except WorkerFilesystemIsolationError as error:
                close_error = error
        try:
            api.close(ruleset_fd)
        except WorkerFilesystemIsolationError as error:
            close_error = error
        if close_error is not None:
            raise close_error
    return WORKER_FILESYSTEM_ISOLATION + (f"landlock_abi_{abi}",)


__all__ = [
    "LANDLOCK_ACCESS_FS_ABI_1",
    "LANDLOCK_ACCESS_FS_ABI_2",
    "LANDLOCK_ACCESS_FS_ABI_3",
    "LANDLOCK_ACCESS_FS_TRUNCATE",
    "LANDLOCK_SYSCALL_NUMBERS",
    "WORKER_FILESYSTEM_ISOLATION",
    "WorkerFilesystemIsolationError",
    "isolate_worker_filesystem",
]
