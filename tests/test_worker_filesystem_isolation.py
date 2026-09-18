"""Worker OS-level filesystem isolation tests."""

from __future__ import annotations

import ctypes
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import core.kernel.worker_filesystem_isolation as filesystem_isolation
from core.kernel.worker_filesystem_isolation import (
    LANDLOCK_ACCESS_FS_ABI_3,
    LANDLOCK_ACCESS_FS_WRITE_FILE,
    WORKER_FILESYSTEM_ISOLATION,
    WorkerFilesystemIsolationError,
    isolate_worker_filesystem,
)


class _FakeApi:
    def __init__(self, *, abi: int = 3, fail_at: str | None = None) -> None:
        self.abi = abi
        self.fail_at = fail_at
        self.ruleset_fd = 900
        self.created: list[int] = []
        self.rules: list[tuple[int, int]] = []
        self.closed: list[int] = []
        self.restricted = False

    def query_abi(self) -> int:
        if self.fail_at == "query":
            raise WorkerFilesystemIsolationError("query failed")
        return self.abi

    def create_ruleset(self, handled_access: int) -> int:
        if self.fail_at == "create":
            raise WorkerFilesystemIsolationError("create failed")
        self.created.append(handled_access)
        return self.ruleset_fd

    def add_rule(self, ruleset_fd: int, allowed_access: int, parent_fd: int) -> None:
        if self.fail_at == "rule":
            raise WorkerFilesystemIsolationError("rule failed")
        self.rules.append((allowed_access, parent_fd))

    def restrict_self(self, ruleset_fd: int) -> None:
        if self.fail_at == "restrict":
            raise WorkerFilesystemIsolationError("restrict failed")
        self.restricted = True

    def close(self, descriptor: int) -> None:
        self.closed.append(descriptor)


class _FakeCFunction:
    def __init__(self, result_factory):
        self.result_factory = result_factory
        self.calls: list[tuple[object, ...]] = []
        self.restype = None
        self.argtypes = None

    def __call__(self, *arguments):
        self.calls.append(arguments)
        return self.result_factory(*arguments)


class _FakeLibc:
    def __init__(self) -> None:
        self.syscall = _FakeCFunction(self._syscall)
        self.prctl = _FakeCFunction(lambda *_arguments: 0)

    def _syscall(self, number, *arguments):
        number = int(number)
        if number == 444 and int(arguments[2].value) == 1:
            return 3
        if number == 444:
            return 900
        return 0


class TestWorkerFilesystemIsolation(unittest.TestCase):
    def test_ctypes_landlock_api_uses_fixed_structures_and_syscalls(self) -> None:
        libc = _FakeLibc()
        with patch.object(ctypes, "CDLL", return_value=libc):
            api = filesystem_isolation._LandlockApi(
                ctypes_module=ctypes, machine_name="x86_64"
            )
            self.assertEqual(api.query_abi(), 3)
            ruleset_fd = api.create_ruleset(LANDLOCK_ACCESS_FS_ABI_3)
            api.add_rule(ruleset_fd, 0, 101)
            api.restrict_self(ruleset_fd)

        self.assertEqual(ruleset_fd, 900)
        self.assertEqual(
            [int(call[0]) for call in libc.syscall.calls], [444, 444, 445, 446]
        )
        self.assertEqual(int(libc.syscall.calls[1][2].value), 8)
        self.assertEqual(
            ctypes.sizeof(
                filesystem_isolation._LandlockPathBeneathAttr(
                    ctypes, 0, 101
                ).value
            ),
            16,
        )
        self.assertEqual(libc.prctl.calls[0][0], 38)

    def test_linux_applies_landlock_and_allows_an_explicit_writable_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = _FakeApi()
            next_fd = iter((101,))
            details = root.stat()
            with (
                patch.object(filesystem_isolation.os, "O_PATH", 0x200000, create=True),
                patch.object(filesystem_isolation.os, "O_DIRECTORY", 0x10000, create=True),
                patch.object(filesystem_isolation.os, "O_NOFOLLOW", 0x20000, create=True),
                patch.object(filesystem_isolation.os, "open", lambda *args: next(next_fd)),
                patch.object(
                    filesystem_isolation.os,
                    "fstat",
                    return_value=SimpleNamespace(
                        st_mode=stat.S_IFDIR,
                        st_dev=details.st_dev,
                        st_ino=details.st_ino,
                    ),
                ),
            ):
                applied = isolate_worker_filesystem(
                    root,
                    platform_name="linux",
                    api_factory=lambda: api,
                    allowed_paths=((root, True),),
                )

            self.assertEqual(applied, WORKER_FILESYSTEM_ISOLATION + ("landlock_abi_3",))
            self.assertEqual(api.created, [LANDLOCK_ACCESS_FS_ABI_3])
            self.assertTrue(api.restricted)
            self.assertEqual(len(api.rules), 1)
            self.assertEqual(api.rules[0][1], 101)
            self.assertTrue(api.rules[0][0] & LANDLOCK_ACCESS_FS_WRITE_FILE)
            self.assertIn(101, api.closed)
            self.assertIn(api.ruleset_fd, api.closed)

    def test_root_writable_is_explicit_and_does_not_change_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = _FakeApi()
            details = root.stat()
            next_fd = iter((101,))
            with (
                patch.object(filesystem_isolation.os, "O_PATH", 0x200000, create=True),
                patch.object(filesystem_isolation.os, "O_DIRECTORY", 0x10000, create=True),
                patch.object(filesystem_isolation.os, "O_NOFOLLOW", 0x20000, create=True),
                patch.object(filesystem_isolation.os, "open", lambda *args: next(next_fd)),
                patch.object(
                    filesystem_isolation.os,
                    "fstat",
                    return_value=SimpleNamespace(
                        st_mode=stat.S_IFDIR,
                        st_dev=details.st_dev,
                        st_ino=details.st_ino,
                    ),
                ),
            ):
                isolate_worker_filesystem(
                    root,
                    platform_name="linux",
                    api_factory=lambda: api,
                    allowed_paths=((root, False),),
                    root_writable=True,
                )

            self.assertTrue(api.rules[0][0] & LANDLOCK_ACCESS_FS_WRITE_FILE)

    def test_default_root_stays_read_only_when_it_matches_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.dict(os.environ, {"TMPDIR": str(root)}, clear=False), patch.object(
                filesystem_isolation.sysconfig, "get_path", return_value=None
            ), patch.object(
                filesystem_isolation.sysconfig, "get_config_var", return_value=None
            ), patch.object(filesystem_isolation.sys, "path", []):
                paths = filesystem_isolation._default_allowed_paths(
                    root,
                    root_writable=False,
                )

            root_entries = [writable for path, writable in paths if path == root]
            self.assertEqual(root_entries, [False])

    def test_plugin_root_is_required_in_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = _FakeApi()
            with self.assertRaises(WorkerFilesystemIsolationError):
                isolate_worker_filesystem(
                    root,
                    platform_name="linux",
                    api_factory=lambda: api,
                    allowed_paths=(),
                )
            self.assertEqual(api.created, [LANDLOCK_ACCESS_FS_ABI_3])
            self.assertFalse(api.restricted)

    def test_newer_landlock_abi_uses_latest_known_access_mask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = _FakeApi(abi=7)
            next_fd = iter((101,))
            details = root.stat()
            with (
                patch.object(filesystem_isolation.os, "O_PATH", 0x200000, create=True),
                patch.object(filesystem_isolation.os, "O_DIRECTORY", 0x10000, create=True),
                patch.object(filesystem_isolation.os, "O_NOFOLLOW", 0x20000, create=True),
                patch.object(filesystem_isolation.os, "open", lambda *args: next(next_fd)),
                patch.object(
                    filesystem_isolation.os,
                    "fstat",
                    return_value=SimpleNamespace(
                        st_mode=stat.S_IFDIR,
                        st_dev=details.st_dev,
                        st_ino=details.st_ino,
                    ),
                ),
            ):
                applied = isolate_worker_filesystem(
                    root,
                    platform_name="linux",
                    api_factory=lambda: api,
                    allowed_paths=((root, False),),
                )

            self.assertEqual(applied, WORKER_FILESYSTEM_ISOLATION + ("landlock_abi_7",))
            self.assertEqual(api.created, [LANDLOCK_ACCESS_FS_ABI_3])
            self.assertTrue(api.restricted)

    def test_invalid_landlock_abi_fails_closed(self) -> None:
        for abi in (0, -1):
            with self.subTest(abi=abi):
                with self.assertRaises(WorkerFilesystemIsolationError):
                    filesystem_isolation._handled_access_for_abi(abi)

    def test_landlock_failures_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for failure in ("query", "create", "rule", "restrict"):
                with self.subTest(failure=failure):
                    api = _FakeApi(fail_at=failure)
                    next_fd = iter((101,))
                    details = root.stat()
                    with (
                        patch.object(filesystem_isolation.os, "O_PATH", 0x200000, create=True),
                        patch.object(filesystem_isolation.os, "O_DIRECTORY", 0x10000, create=True),
                        patch.object(filesystem_isolation.os, "O_NOFOLLOW", 0x20000, create=True),
                        patch.object(filesystem_isolation.os, "open", lambda *args: next(next_fd)),
                        patch.object(
                            filesystem_isolation.os,
                            "fstat",
                            return_value=SimpleNamespace(
                                st_mode=stat.S_IFDIR,
                                st_dev=details.st_dev,
                                st_ino=details.st_ino,
                            ),
                        ),
                    ):
                        with self.assertRaises(WorkerFilesystemIsolationError):
                            isolate_worker_filesystem(
                                root,
                                platform_name="linux",
                                api_factory=lambda: api,
                                allowed_paths=((root, True),),
                            )
                    self.assertFalse(api.restricted)
                    if failure in {"rule", "restrict"}:
                        self.assertIn(101, api.closed)
                        self.assertIn(api.ruleset_fd, api.closed)

    def test_non_linux_platforms_remain_explicitly_unsupported(self) -> None:
        for platform_name in ("win32", "darwin"):
            with self.subTest(platform=platform_name):
                self.assertEqual(
                    isolate_worker_filesystem(
                        Path(os.getcwd()), platform_name=platform_name
                    ),
                    (),
                )


if __name__ == "__main__":
    unittest.main()
