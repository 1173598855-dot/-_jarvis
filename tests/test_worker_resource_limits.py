"""Worker OS-level resource limit tests."""

import os
import subprocess
import sys
import unittest

from core.kernel import worker_resource_limits


class _FakeResourceModule:
    RLIMIT_CORE = 4
    RLIMIT_FSIZE = 1
    RLIMIT_NOFILE = 7

    def __init__(self, current=None, failures=(), missing=()):
        self._current = dict(current or {})
        self._failures = set(failures)
        self.applied = []
        for attribute in missing:
            setattr(self, attribute, None)

    def getrlimit(self, key):
        return self._current.get(key, (self.RLIM_INFINITY, self.RLIM_INFINITY))

    def setrlimit(self, key, limits):
        if key in self._failures:
            raise ValueError("not permitted")
        self.applied.append((key, limits))
        self._current[key] = limits

    RLIM_INFINITY = -1


class TestWorkerResourceLimits(unittest.TestCase):
    def test_declared_budgets_are_fixed_and_positive(self):
        budgets = worker_resource_limits.WORKER_RESOURCE_BUDGETS

        self.assertEqual(budgets["core_bytes"], 0)
        self.assertEqual(budgets["file_bytes"], 64 * 1024 * 1024)
        self.assertEqual(budgets["open_files"], 256)
        self.assertNotIn("processes", budgets)

    def test_posix_limits_lower_both_soft_and_hard_bounds(self):
        resource = _FakeResourceModule()

        applied = worker_resource_limits.apply_worker_resource_limits(
            resource_module=resource,
            platform_name="posix",
        )

        budgets = worker_resource_limits.WORKER_RESOURCE_BUDGETS
        self.assertEqual(
            dict(resource.applied),
            {
                resource.RLIMIT_CORE: (0, 0),
                resource.RLIMIT_FSIZE: (
                    budgets["file_bytes"],
                    budgets["file_bytes"],
                ),
                resource.RLIMIT_NOFILE: (
                    budgets["open_files"],
                    budgets["open_files"],
                ),
            },
        )
        self.assertEqual(
            sorted(applied),
            ["core_bytes", "file_bytes", "open_files"],
        )

    def test_posix_limits_never_raise_an_already_stricter_bound(self):
        resource = _FakeResourceModule(
            current={
                _FakeResourceModule.RLIMIT_NOFILE: (64, 64),
                _FakeResourceModule.RLIMIT_FSIZE: (1024, 1024),
            }
        )

        worker_resource_limits.apply_worker_resource_limits(
            resource_module=resource,
            platform_name="posix",
        )

        applied = dict(resource.applied)
        self.assertEqual(applied[resource.RLIMIT_NOFILE], (64, 64))
        self.assertEqual(applied[resource.RLIMIT_FSIZE], (1024, 1024))

    def test_posix_limit_failure_fails_closed(self):
        resource = _FakeResourceModule(
            failures={_FakeResourceModule.RLIMIT_NOFILE},
        )

        with self.assertRaises(worker_resource_limits.WorkerResourceLimitError):
            worker_resource_limits.apply_worker_resource_limits(
                resource_module=resource,
                platform_name="posix",
            )

    def test_missing_platform_limits_are_skipped_without_failing(self):
        resource = _FakeResourceModule(missing=("RLIMIT_FSIZE",))

        applied = worker_resource_limits.apply_worker_resource_limits(
            resource_module=resource,
            platform_name="posix",
        )

        self.assertNotIn("file_bytes", applied)
        self.assertIn("open_files", applied)

    def test_windows_defers_to_parent_owned_job_object(self):
        resource = _FakeResourceModule()

        applied = worker_resource_limits.apply_worker_resource_limits(
            resource_module=resource,
            platform_name="nt",
        )

        self.assertEqual(applied, ())
        self.assertEqual(resource.applied, [])

    @unittest.skipIf(os.name == "nt", "POSIX rlimit enforcement")
    def test_posix_worker_child_enforces_the_real_budget(self):
        script = (
            "import resource, sys\n"
            "sys.path.insert(0, %r)\n" % str(
                __import__("pathlib").Path(worker_resource_limits.__file__)
                .resolve()
                .parents[3]
            )
            + "from core.kernel.worker_resource_limits import "
            "apply_worker_resource_limits\n"
            "apply_worker_resource_limits()\n"
            "print(resource.getrlimit(resource.RLIMIT_NOFILE)[1])\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        # Budgets only ever lower a bound, so a stricter host stays stricter.
        self.assertLessEqual(
            int(completed.stdout.strip()),
            worker_resource_limits.WORKER_RESOURCE_BUDGETS["open_files"],
        )


if __name__ == "__main__":
    unittest.main()
