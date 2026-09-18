"""Platform process-tree containment tests."""

import ctypes
import signal
import subprocess
import sys
import unittest
from unittest.mock import call, patch

from core.kernel import process_containment


class _FakeProcess:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid


class _FakeJobApi:
    def __init__(self, active: list[int]) -> None:
        self._active = iter(active)
        self.close_calls: list[int] = []

    def active_processes(self, _job_handle: int) -> int:
        return next(self._active)

    def close(self, job_handle: int) -> bool:
        self.close_calls.append(job_handle)
        return True


class TestProcessTreeContainment(unittest.TestCase):
    def test_posix_close_refuses_while_owned_group_is_active(self):
        process = _FakeProcess()
        with (
            patch.object(process_containment.os, "killpg", create=True) as killpg,
        ):
            killpg.side_effect = [None, ProcessLookupError()]
            containment = process_containment.ProcessTreeContainment(
                process,
                process_group_id=process.pid,
            )

            self.assertFalse(containment.close())
            self.assertTrue(containment.is_attached)
            self.assertTrue(containment.close())
            self.assertFalse(containment.is_attached)

        self.assertEqual(
            killpg.call_args_list,
            [
                call(process.pid, 0),
                call(process.pid, 0),
            ],
        )

    def test_windows_close_keeps_job_handle_until_tree_is_empty(self):
        process = _FakeProcess()
        job_api = _FakeJobApi([1, 0])
        containment = process_containment.ProcessTreeContainment(
            process,
            job_api=job_api,
            job_handle=77,
        )

        self.assertFalse(containment.close())
        self.assertTrue(containment.is_attached)
        self.assertTrue(containment.close())
        self.assertFalse(containment.is_attached)
        self.assertEqual(job_api.close_calls, [77])

    def test_posix_boundary_signals_the_owned_process_group(self):
        containment_type = getattr(
            process_containment,
            "ProcessTreeContainment",
            None,
        )
        self.assertIsNotNone(containment_type)
        process = _FakeProcess()

        with (
            patch.object(process_containment, "_POPEN_TYPE", _FakeProcess),
            patch.object(process_containment.os, "name", "posix"),
            patch.object(
                process_containment.os,
                "getpgid",
                return_value=process.pid,
                create=True,
            ),
            patch.object(process_containment.os, "killpg", create=True) as killpg,
        ):
            containment = containment_type.attach(process)
            self.assertTrue(containment.terminate(force=False))
            self.assertTrue(containment.terminate(force=True))

        self.assertEqual(
            killpg.call_args_list,
            [
                call(process.pid, signal.SIGTERM),
                call(process.pid, getattr(signal, "SIGKILL", 9)),
            ],
        )

    def test_windows_job_declares_memory_and_process_budgets(self):
        self.assertEqual(
            process_containment._JOB_OBJECT_LIMIT_PROCESS_MEMORY,
            0x100,
        )
        self.assertEqual(
            process_containment._JOB_OBJECT_LIMIT_JOB_MEMORY,
            0x200,
        )
        self.assertEqual(
            process_containment._JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
            0x8,
        )

    def test_windows_job_creation_applies_the_declared_budgets(self):
        recorded = {}

        class _StubJobApi(process_containment._WindowsJobApi):
            def __init__(self) -> None:
                pass

            def _create_job(self, _attributes, _name):
                return 4242

            def _set_information(self, handle, info_class, payload, size):
                recorded["handle"] = handle
                recorded["class"] = info_class
                recorded["limits"] = ctypes.cast(
                    payload,
                    ctypes.POINTER(
                        process_containment._JobObjectExtendedLimitInformation
                    ),
                ).contents
                recorded["size"] = size
                return 1

            def _close_handle(self, _handle):
                return 1

        handle = _StubJobApi().create()
        limits = recorded["limits"]
        budgets = process_containment.WORKER_PROCESS_TREE_BUDGETS

        self.assertEqual(handle, 4242)
        self.assertEqual(
            recorded["class"],
            process_containment._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        )
        flags = limits.BasicLimitInformation.LimitFlags
        self.assertTrue(flags & process_containment._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        self.assertTrue(flags & process_containment._JOB_OBJECT_LIMIT_PROCESS_MEMORY)
        self.assertTrue(flags & process_containment._JOB_OBJECT_LIMIT_JOB_MEMORY)
        self.assertTrue(flags & process_containment._JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
        self.assertEqual(limits.ProcessMemoryLimit, budgets["process_memory_bytes"])
        self.assertEqual(limits.JobMemoryLimit, budgets["job_memory_bytes"])
        self.assertEqual(
            limits.BasicLimitInformation.ActiveProcessLimit,
            budgets["active_processes"],
        )

    def test_windows_job_budgets_are_fixed_and_positive(self):
        budgets = process_containment.WORKER_PROCESS_TREE_BUDGETS

        self.assertEqual(budgets["process_memory_bytes"], 1024 * 1024 * 1024)
        self.assertEqual(budgets["job_memory_bytes"], 1024 * 1024 * 1024)
        self.assertEqual(budgets["active_processes"], 64)

    def test_non_popen_test_double_does_not_claim_os_containment(self):
        process = _FakeProcess()

        self.assertIsNone(process_containment.ProcessTreeContainment.attach(process))

    def test_posix_attachment_rejects_a_worker_outside_its_own_group(self):
        process = _FakeProcess()
        with (
            patch.object(process_containment, "_POPEN_TYPE", _FakeProcess),
            patch.object(process_containment.os, "name", "posix"),
            patch.object(
                process_containment.os,
                "getpgid",
                return_value=process.pid + 1,
                create=True,
            ),
        ):
            with self.assertRaises(process_containment.ProcessContainmentError):
                process_containment.ProcessTreeContainment.attach(process)

    @unittest.skipUnless(sys.platform == "win32", "Windows Job Object regression")
    def test_windows_job_owns_descendant_after_worker_exits(self):
        script = (
            "import subprocess, sys\n"
            "sys.stdin.readline()\n"
            "subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(60)'])\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **process_containment.process_group_popen_kwargs(),
        )
        containment = process_containment.ProcessTreeContainment.attach(process)
        self.assertIsNotNone(containment)
        try:
            process.stdin.write("spawn\n")
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=5)

            self.assertFalse(containment.wait_empty(0.05))
            self.assertTrue(containment.terminate(force=True))
            self.assertTrue(containment.wait_empty(5))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            containment.terminate(force=True)
            containment.wait_empty(5)
            containment.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

        self.assertFalse(containment.is_attached)


if __name__ == "__main__":
    unittest.main()
