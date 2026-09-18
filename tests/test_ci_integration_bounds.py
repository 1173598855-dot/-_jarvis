"""Deadline, fail-fast and reclamation tests for the CI integration runner."""

from __future__ import annotations

import importlib.util
import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
RUNNER = ROOT / "scripts" / "ci_local_integration.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("jarvis_ci_runner_bounds", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeService:
    """A service that never dies and never needs reaping."""

    pid = None

    def __init__(self, returncode=None) -> None:
        self._returncode = returncode
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return self._returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._returncode = -15

    def wait(self, timeout=None):
        del timeout
        if self._returncode is None:
            self._returncode = 0
        return self._returncode

    def kill(self) -> None:
        self.kill_calls += 1
        self._returncode = -9


class TestOverallDeadlineAccounting(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_stage_budget_is_capped_by_the_overall_remainder(self) -> None:
        deadline = time.monotonic() + 2
        self.assertLessEqual(self.runner._stage_budget(deadline, "stage", 30.0), 2.0)

    def test_stage_budget_keeps_its_own_budget_when_the_remainder_is_larger(self) -> None:
        deadline = time.monotonic() + 600
        self.assertEqual(self.runner._stage_budget(deadline, "stage", 30.0), 30.0)

    def test_absent_deadline_leaves_the_stage_budget_untouched(self) -> None:
        self.assertEqual(self.runner._stage_budget(None, "stage", 30.0), 30.0)
        self.assertIsNone(self.runner._remaining(None, "stage"))

    def test_exhausted_deadline_fails_closed_naming_the_stage(self) -> None:
        deadline = time.monotonic() - 1
        with self.assertRaises(self.runner.IntegrationTimeout) as raised:
            self.runner._stage_budget(deadline, "profile", 30.0)

        self.assertIn("profile", str(raised.exception))


class TestHealthWaitFailsFast(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.dead_port = int(probe.getsockname()[1])
        self.url = f"http://127.0.0.1:{self.dead_port}/api/health"

    def test_exited_service_is_reported_before_the_budget_is_spent(self) -> None:
        service = _FakeService(returncode=3)
        started = time.monotonic()

        with self.assertRaises(RuntimeError) as raised:
            self.runner._wait_for_health(self.url, 20, service, "core")
        elapsed = time.monotonic() - started

        message = str(raised.exception)
        self.assertIn("core", message)
        self.assertIn("3", message)
        # Without fail-fast this polled a dead port for the full 20 seconds.
        self.assertLess(elapsed, 5)

    def test_unreachable_but_live_service_still_times_out_with_its_label(self) -> None:
        service = _FakeService()

        with self.assertRaises(RuntimeError) as raised:
            self.runner._wait_for_health(self.url, 1, service, "express")

        message = str(raised.exception)
        self.assertIn("express", message)
        self.assertIn("Timed out", message)

    def test_process_argument_stays_optional(self) -> None:
        with self.assertRaises(RuntimeError):
            self.runner._wait_for_health(self.url, 1)


class TestProfileRunsUnderItsBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        self.directory = tempfile.mkdtemp(prefix="ci-bounds-")
        self.addCleanup(_rmtree, self.directory)

    def _sleeper(self, seconds: int) -> Path:
        path = Path(self.directory, "sleeper.py")
        path.write_text(f"import time\ntime.sleep({seconds})\n", encoding="utf-8")
        return path

    def test_overrunning_profile_is_killed_at_its_budget(self) -> None:
        sleeper = self._sleeper(60)
        started = time.monotonic()

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.runner, "PROFILE", sleeper):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.runner._run_profile(
                    express_url="http://127.0.0.1:1",
                    timeout=1,
                    env=dict(os.environ),
                    budget=2.0,
                    services=[],
                )
        elapsed = time.monotonic() - started

        self.assertEqual(code, 2)
        # The profile sleeps for 60s; the budget must cut it short.
        self.assertLess(elapsed, 25)
        self.assertIn("exceeded", stderr.getvalue())

    def test_profile_exit_code_passes_through_when_it_finishes_in_time(self) -> None:
        path = Path(self.directory, "quick.py")
        path.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")

        with patch.object(self.runner, "PROFILE", path):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = self.runner._run_profile(
                    express_url="http://127.0.0.1:1",
                    timeout=1,
                    env=dict(os.environ),
                    budget=60.0,
                    services=[],
                )

        self.assertEqual(code, 7)


class TestRunIntegrationBoundsTheWholeRun(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        self.directory = tempfile.mkdtemp(prefix="ci-bounds-run-")
        self.addCleanup(_rmtree, self.directory)

    def test_a_wedged_profile_cannot_outlive_the_overall_timeout(self) -> None:
        sleeper = Path(self.directory, "sleeper.py")
        sleeper.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
        fake_popen = _fake_only_services(subprocess.Popen)
        started = time.monotonic()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.runner, "PROFILE", sleeper), \
                patch.object(self.runner, "_wait_for_health", _accept_any), \
                patch.object(self.runner.subprocess, "Popen", fake_popen):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.runner.run_integration(timeout=2, overall_timeout=6)
        elapsed = time.monotonic() - started

        self.assertEqual(code, 2)
        # Before the fix this waited the full 120 seconds regardless of --timeout.
        self.assertLess(elapsed, 40)

    def test_exhausted_overall_deadline_is_reported_not_raised(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()

        def slow_health(*args, **kwargs):
            del args, kwargs
            time.sleep(1.5)

        with patch.object(self.runner, "_wait_for_health", slow_health), \
                patch.object(
                    self.runner.subprocess,
                    "Popen",
                    _fake_only_services(subprocess.Popen),
                ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.runner.run_integration(timeout=5, overall_timeout=1)

        self.assertEqual(code, 2)
        self.assertIn("overall timeout exhausted", stderr.getvalue())

    def test_rejects_optional_services_mode(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.run_integration(require_services=False)


class TestParserBounds(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_overall_timeout_is_exposed_with_a_positive_default(self) -> None:
        arguments = self.runner.build_parser().parse_args([])

        self.assertEqual(arguments.timeout, 30)
        self.assertGreater(arguments.overall_timeout, 0)
        self.assertIn("--overall-timeout", self.runner.build_parser().format_help())

    def test_non_positive_and_non_integer_timeouts_are_rejected(self) -> None:
        parser = self.runner.build_parser()
        for flag in ("--timeout", "--overall-timeout"):
            for value in ("0", "-1", "abc", "1.5"):
                with self.subTest(flag=flag, value=value):
                    with self.assertRaises(SystemExit) as raised:
                        with redirect_stderr(io.StringIO()):
                            parser.parse_args([flag, value])
                    self.assertEqual(raised.exception.code, 2)


class TestTreeReclamation(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_terminate_tree_tolerates_a_finished_child(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait(timeout=60)

        self.runner._terminate_tree(process)

    def test_terminate_tree_tolerates_an_object_without_a_pid(self) -> None:
        self.runner._terminate_tree(object())

    def test_stop_escalates_to_a_tree_kill_when_terminate_is_ignored(self) -> None:
        service = _FakeService()

        def refuse_wait(timeout=None):
            del timeout
            raise subprocess.TimeoutExpired(cmd="service", timeout=1)

        service.wait = refuse_wait
        with patch.object(self.runner, "_terminate_tree") as tree_kill:
            self.runner._stop(service)

        self.assertEqual(service.terminate_calls, 1)
        tree_kill.assert_called_once_with(service)

    def test_stop_ignores_an_already_exited_service(self) -> None:
        service = _FakeService(returncode=0)

        self.runner._stop(service)

        self.assertEqual(service.terminate_calls, 0)


class TestServiceLogTails(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        self.directory = tempfile.mkdtemp(prefix="ci-bounds-log-")
        self.addCleanup(_rmtree, self.directory)

    def test_log_tail_is_bounded_to_the_final_bytes(self) -> None:
        path = Path(self.directory, "core.log")
        path.write_bytes(b"A" * 10_000 + b"TAIL_MARKER")

        tail = self.runner._read_log_tail(path)

        self.assertIn("TAIL_MARKER", tail)
        self.assertLessEqual(len(tail.encode("utf-8")), self.runner._LOG_TAIL_BYTES)

    def test_missing_log_is_not_an_error(self) -> None:
        self.assertEqual(self.runner._read_log_tail(Path(self.directory, "absent.log")), "")
        self.assertEqual(self.runner._read_log_tail(None), "")

    def test_service_output_is_reported_on_failure(self) -> None:
        path = Path(self.directory, "express.log")
        path.write_text("EADDRINUSE 127.0.0.1:9999", encoding="utf-8")
        service = self.runner._Service("express", _FakeService(returncode=1), path)

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.runner._report_service_logs([service])

        output = stderr.getvalue()
        self.assertIn("express", output)
        self.assertIn("EADDRINUSE", output)


_SERVICE_MARKERS = ("local_ollama_fixture", "uvicorn", "server.js")


def _fake_only_services(real_popen):
    """Fake the three long-lived services and let every other child be real.

    Patching Popen on the shared subprocess module also intercepts the
    reclamation helper's own taskkill call, so anything that is not a known
    service must pass through untouched.
    """

    def popen(command, *args, **kwargs):
        text = " ".join(str(part) for part in command)
        if any(marker in text for marker in _SERVICE_MARKERS):
            return _FakeService()
        return real_popen(command, *args, **kwargs)

    return popen


def _accept_any(*args, **kwargs):
    del args, kwargs
    return None


def _rmtree(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
