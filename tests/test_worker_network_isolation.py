"""Worker OS-level network isolation tests."""

from __future__ import annotations

import errno
import os
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

import core.kernel.worker_network_isolation as network_isolation
from core.kernel.worker_network_isolation import (
    CLONE_NEWNET,
    WORKER_NETWORK_ISOLATION,
    WorkerNetworkIsolationError,
    isolate_worker_network,
)


class _FakeLibc:
    def __init__(
        self,
        *,
        missing_symbol: bool = False,
        results: tuple[int, ...] = (0,),
    ) -> None:
        self.results = iter(results)
        self.calls: list[int] = []
        if not missing_symbol:
            self.unshare = lambda flag: self._unshare(flag)

    def _unshare(self, flag: int) -> int:
        self.calls.append(flag)
        return next(self.results)


def _ctypes(libc: _FakeLibc, errno: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        CDLL=lambda _name, *, use_errno: libc,
        c_int=int,
        get_errno=lambda: errno,
    )


class TestWorkerNetworkIsolation(unittest.TestCase):
    def test_declares_a_single_fixed_linux_boundary(self) -> None:
        self.assertEqual(WORKER_NETWORK_ISOLATION, ("network_namespace",))
        self.assertEqual(CLONE_NEWNET, 0x40000000)
        self.assertEqual(getattr(network_isolation, "CLONE_NEWUSER", None), 0x10000000)

    def test_linux_enters_an_isolated_network_namespace(self) -> None:
        libc = _FakeLibc()

        with patch.object(
            network_isolation, "_map_current_identity", create=True
        ) as mapper:
            applied = isolate_worker_network(
                ctypes_module=_ctypes(libc),
                platform_name="linux",
            )

        self.assertEqual(applied, WORKER_NETWORK_ISOLATION)
        self.assertEqual(libc.calls, [CLONE_NEWNET])
        mapper.assert_not_called()

    def test_permission_failure_retries_in_a_mapped_user_namespace(self) -> None:
        libc = _FakeLibc(results=(-1, 0))

        with (
            patch.object(os, "geteuid", return_value=1001, create=True),
            patch.object(os, "getegid", return_value=1002, create=True),
            patch.object(
                network_isolation, "_map_current_identity", create=True
            ) as mapper,
        ):
            try:
                applied = isolate_worker_network(
                    ctypes_module=_ctypes(libc, errno=errno.EPERM),
                    platform_name="linux",
                )
            except WorkerNetworkIsolationError as error:
                self.fail(f"EPERM did not enter the user-namespace fallback: {error}")

        self.assertEqual(applied, WORKER_NETWORK_ISOLATION)
        self.assertEqual(libc.calls, [CLONE_NEWNET, 0x10000000 | CLONE_NEWNET])
        mapper.assert_called_once_with(1001, 1002)

    def test_permission_fallback_captures_identity_before_entering_user_namespace(self) -> None:
        libc = _FakeLibc(results=(-1, 0))

        def identity_after_namespace() -> int:
            # A process in an unmapped user namespace can report overflow IDs.
            return 65534 if len(libc.calls) > 1 else 1001

        with (
            patch.object(
                os, "geteuid", side_effect=identity_after_namespace, create=True
            ),
            patch.object(
                os, "getegid", side_effect=identity_after_namespace, create=True
            ),
            patch.object(network_isolation, "_map_current_identity", create=True) as mapper,
        ):
            isolate_worker_network(
                ctypes_module=_ctypes(libc, errno=errno.EPERM),
                platform_name="linux",
            )

        mapper.assert_called_once_with(1001, 1001)

    def test_failure_fails_closed_with_errno(self) -> None:
        libc = _FakeLibc(results=(-1,))

        with self.assertRaises(WorkerNetworkIsolationError) as context:
            isolate_worker_network(
                ctypes_module=_ctypes(libc, errno=38),
                platform_name="linux",
            )

        self.assertIn("38", str(context.exception))
        self.assertEqual(libc.calls, [CLONE_NEWNET])

    def test_user_namespace_or_identity_mapping_failure_fails_closed(self) -> None:
        for results, mapping_error in (
            ((-1, -1), None),
            ((-1, 0), WorkerNetworkIsolationError("mapping failed")),
        ):
            with self.subTest(results=results):
                libc = _FakeLibc(results=results)
                with patch.object(
                    network_isolation,
                    "_map_current_identity",
                    side_effect=mapping_error,
                    create=True,
                ) as mapper, patch.object(
                    os, "geteuid", return_value=1001, create=True
                ), patch.object(
                    os, "getegid", return_value=1002, create=True
                ):
                    with self.assertRaises(WorkerNetworkIsolationError):
                        isolate_worker_network(
                            ctypes_module=_ctypes(libc, errno=errno.EPERM),
                            platform_name="linux",
                        )
                self.assertEqual(
                    libc.calls,
                    [CLONE_NEWNET, 0x10000000 | CLONE_NEWNET],
                )
                if results[-1] == 0:
                    mapper.assert_called_once()
                else:
                    mapper.assert_not_called()

    def test_current_identity_mapping_writes_fixed_proc_controls(self) -> None:
        with patch.object(network_isolation, "_write_namespace_control") as writer:
            network_isolation._map_current_identity(1001, 1002)

        self.assertEqual(
            writer.call_args_list,
            [
                call("/proc/self/setgroups", b"deny\n"),
                call("/proc/self/uid_map", b"1001 1001 1\n"),
                call("/proc/self/gid_map", b"1002 1002 1\n"),
            ],
        )

    def test_namespace_control_write_rejects_short_write_and_close_failure(self) -> None:
        with (
            patch.object(network_isolation.os, "open", return_value=91),
            patch.object(network_isolation.os, "write", return_value=1),
            patch.object(network_isolation.os, "close") as close,
        ):
            with self.assertRaises(WorkerNetworkIsolationError):
                network_isolation._write_namespace_control("/proc/self/uid_map", b"123")
        close.assert_called_once_with(91)

        with (
            patch.object(network_isolation.os, "open", return_value=92),
            patch.object(network_isolation.os, "write", return_value=3),
            patch.object(network_isolation.os, "close", side_effect=OSError("close failed")),
        ):
            with self.assertRaises(WorkerNetworkIsolationError):
                network_isolation._write_namespace_control("/proc/self/uid_map", b"123")

    def test_missing_kernel_symbol_fails_closed(self) -> None:
        with self.assertRaises(WorkerNetworkIsolationError):
            isolate_worker_network(
                ctypes_module=_ctypes(_FakeLibc(missing_symbol=True)),
                platform_name="linux",
            )

    def test_non_linux_platforms_are_currently_unsupported(self) -> None:
        for platform_name in ("win32", "darwin"):
            with self.subTest(platform=platform_name):
                self.assertEqual(
                    isolate_worker_network(
                        ctypes_module=None,
                        platform_name=platform_name,
                    ),
                    (),
                )
