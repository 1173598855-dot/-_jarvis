"""Bounded-deadline and hang-attribution tests for the discovery runner."""

from __future__ import annotations

import io
import json
import locale
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import discover_tests

SCRIPT = Path(discover_tests.__file__).resolve()

_PASSING_FIXTURE = """import unittest


class TestFixture(unittest.TestCase):
    def test_documented(self):
        \"\"\"Documented case.\"\"\"
        self.assertTrue(True)

    def test_plain(self):
        self.assertTrue(True)
"""

_UTF8_OUTPUT_FIXTURE = """import unittest


class TestFixture(unittest.TestCase):
    def test_non_ascii_diagnostic(self):
        \"\"\"Pound sign: £.\"\"\"
        self.assertTrue(True)
"""

_INVALID_UTF8_OUTPUT_FIXTURE = r"""import sys
import unittest


class TestFixture(unittest.TestCase):
    def test_invalid_utf8_diagnostic(self):
        sys.stdout.buffer.write(b"invalid:\xff\n")
        sys.stdout.buffer.flush()
"""

_HANGING_FIXTURE = """import time
import unittest


class TestFixture(unittest.TestCase):
    def test_first(self):
        self.assertTrue(True)

    def test_hangs(self):
        time.sleep(30)
"""

_GRANDCHILD_SCRIPT = """import time
from pathlib import Path

BEAT = Path(__file__).resolve().parent / "beat.txt"
for _ in range(600):
    with BEAT.open("a", encoding="utf-8") as handle:
        handle.write("x")
    time.sleep(0.1)
"""

_GRANDCHILD_FIXTURE = """import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class TestFixture(unittest.TestCase):
    def test_spawns_a_grandchild_then_hangs(self):
        subprocess.Popen(
            [sys.executable, str(HERE / "grandchild.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(30)
"""


_FAILING_FIXTURE = """import unittest


class TestFixture(unittest.TestCase):
    def test_fails(self):
        self.fail("intentional")
"""


class _DiscoveryFixtureMixin(unittest.TestCase):
    def make_fixture(self, body: str) -> str:
        directory = tempfile.mkdtemp(prefix="discover-runner-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        Path(directory, "test_fixture.py").write_text(body, encoding="utf-8")
        return directory

    def report_path(self) -> str:
        handle, path = tempfile.mkstemp(suffix=".json", prefix="discover-report-")
        os.close(handle)
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        return path

    def load_report(self, path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def run_script(self, arguments: list) -> tuple:
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)] + arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
            timeout=120,
        )
        return completed, time.monotonic() - started


class TestDiscoveryProgress(unittest.TestCase):
    def test_tracks_the_in_flight_test_until_its_outcome_arrives(self) -> None:
        progress = discover_tests._DiscoveryProgress()
        progress.feed("test_a (mod.T.test_a) ... ")

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["in_flight"], "test_a (mod.T.test_a)")
        self.assertEqual(snapshot["completed"], 0)

        progress.feed("ok\n")

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["in_flight"], "")
        self.assertEqual(snapshot["completed"], 1)
        self.assertEqual(snapshot["recent"], ["test_a (mod.T.test_a) ... ok"])

    def test_pairs_a_docstring_line_with_the_preceding_test_id(self) -> None:
        progress = discover_tests._DiscoveryProgress()
        progress.feed("test_a (mod.T.test_a)\nDocumented case. ... ")

        self.assertEqual(
            progress.snapshot()["in_flight"],
            "test_a (mod.T.test_a) :: Documented case.",
        )

        progress.feed("ok\n")

        snapshot = progress.snapshot()
        self.assertEqual(
            snapshot["recent"],
            ["test_a (mod.T.test_a) :: Documented case. ... ok"],
        )
        self.assertEqual(snapshot["in_flight"], "")

    def test_records_skipped_failed_and_errored_outcomes(self) -> None:
        progress = discover_tests._DiscoveryProgress()
        progress.feed(
            "test_a (mod.T.test_a) ... skipped 'why'\n"
            "test_b (mod.T.test_b) ... FAIL\n"
            "test_c (mod.T.test_c) ... ERROR\n"
            "test_d (mod.T.test_d) ... expected failure\n"
        )

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["completed"], 4)
        self.assertEqual(snapshot["in_flight"], "")
        self.assertEqual(
            snapshot["recent"][0], "test_a (mod.T.test_a) ... skipped 'why'"
        )
        self.assertEqual(snapshot["recent"][-1], "test_d (mod.T.test_d) ... expected failure")

    def test_reassembles_lines_split_across_reads(self) -> None:
        progress = discover_tests._DiscoveryProgress()
        for character in "test_a (mod.T.test_a) ... ok\n":
            progress.feed(character)

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["completed"], 1)
        self.assertEqual(snapshot["recent"], ["test_a (mod.T.test_a) ... ok"])

    def test_recent_results_stay_bounded_while_the_total_keeps_counting(self) -> None:
        progress = discover_tests._DiscoveryProgress()
        total = discover_tests._RECENT_TEST_LIMIT + 5
        for index in range(total):
            progress.feed(f"test_{index} (mod.T.test_{index}) ... ok\n")

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["completed"], total)
        self.assertEqual(len(snapshot["recent"]), discover_tests._RECENT_TEST_LIMIT)
        self.assertEqual(snapshot["recent"][0], "test_5 (mod.T.test_5) ... ok")

    def test_records_the_authoritative_summary_count(self) -> None:
        progress = discover_tests._DiscoveryProgress()
        progress.feed(
            "test_a (mod.T.test_a) ... ok\n"
            "----------------------------------------------------------------------\n"
            "Ran 1 test in 0.001s\n"
            "\nOK\n"
        )

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["ran_tests"], 1)
        self.assertEqual(snapshot["outcome"], "OK")

    def test_the_outer_summary_wins_over_a_nested_runner_summary(self) -> None:
        # Coverage tests spawn nested runners that write their own summary to
        # the same stream, so only the final summary describes this discovery.
        progress = discover_tests._DiscoveryProgress()
        progress.feed(
            "Ran 36 tests in 0.7s\n"
            "\nFAILED (failures=2)\n"
            "Ran 2014 tests in 176.4s\n"
            "\nFAILED (failures=3, skipped=6)\n"
        )

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["ran_tests"], 2014)
        self.assertEqual(snapshot["outcome"], "FAILED (failures=3, skipped=6)")

    def test_summary_count_survives_output_that_breaks_attribution(self) -> None:
        # A test writing a bare newline to stderr splits the pending progress
        # line, so per-test attribution can undercount while the trailing
        # unittest summary stays exact.
        progress = discover_tests._DiscoveryProgress()
        progress.feed("test_a (mod.T.test_a) ... ")
        progress.feed("\nstray output\nok\n")
        progress.feed("Ran 1 test in 0.5s\n\nOK\n")

        snapshot = progress.snapshot()
        self.assertEqual(snapshot["completed"], 0)
        self.assertEqual(snapshot["ran_tests"], 1)
        self.assertEqual(snapshot["outcome"], "OK")

    def test_summary_lines_are_not_counted_as_tests(self) -> None:
        progress = discover_tests._DiscoveryProgress()
        progress.feed(
            "test_a (mod.T.test_a) ... ok\n"
            "----------------------------------------------------------------------\n"
            "Ran 1 test in 0.001s\n"
            "\nOK\n"
        )

        self.assertEqual(progress.snapshot()["completed"], 1)


class TestDiscoveryCommand(unittest.TestCase):
    def test_command_forces_unbuffered_verbose_discovery(self) -> None:
        command = discover_tests.discovery_command("tests", "test_*.py")

        self.assertEqual(command[0], sys.executable)
        # Verbose output is what makes per-test hang attribution possible, and
        # unbuffered output is what makes it available before the deadline.
        self.assertIn("-u", command)
        self.assertIn("-v", command)
        self.assertEqual(command[2:6], ["-m", "unittest", "discover", "-v"])
        self.assertEqual(command[6:], ["-s", "tests", "-p", "test_*.py"])

    def test_parser_defaults_match_the_documented_baseline(self) -> None:
        arguments = discover_tests.build_argument_parser().parse_args([])

        self.assertEqual(arguments.timeout, 0)
        self.assertEqual(arguments.json_report, "")
        self.assertEqual(arguments.start_directory, "tests")
        self.assertEqual(arguments.pattern, "test_*.py")

    def test_parser_accepts_the_ci_flags(self) -> None:
        arguments = discover_tests.build_argument_parser().parse_args(
            ["--timeout", "1800", "--json-report", "report.json"]
        )

        self.assertEqual(arguments.timeout, 1800)
        self.assertEqual(arguments.json_report, "report.json")

    def test_parser_rejects_negative_and_non_integer_timeouts(self) -> None:
        parser = discover_tests.build_argument_parser()
        for value in ("-1", "abc", "1.5"):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit) as raised:
                    with redirect_stderr(io.StringIO()):
                        parser.parse_args(["--timeout", value])
                self.assertEqual(raised.exception.code, 2)


class TestTerminateProcessTree(unittest.TestCase):
    def test_tolerates_an_already_finished_child(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait(timeout=60)

        discover_tests._terminate_process_tree(process)

    def test_tolerates_an_object_without_a_pid(self) -> None:
        discover_tests._terminate_process_tree(object())


class TestRunDiscoveryInProcess(_DiscoveryFixtureMixin):
    def run_discovery_quietly(self, **kwargs) -> tuple:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = discover_tests.run_discovery(**kwargs)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_stream_overflow_fails_closed(self) -> None:
        directory = self.make_fixture(_PASSING_FIXTURE)
        report = self.report_path()

        code, _stdout, _stderr = self.run_discovery_quietly(
            timeout=120,
            json_report=report,
            start_directory=directory,
            stream_limit=32,
        )

        payload = self.load_report(report)
        self.assertEqual(code, 1)
        self.assertTrue(payload["output_limited"])
        self.assertFalse(payload["success"])
        self.assertFalse(payload["timeout_expired"])

    def test_missing_start_directory_fails_closed(self) -> None:
        report = self.report_path()
        missing = str(Path(tempfile.gettempdir(), "discover-runner-absent"))

        code, _stdout, _stderr = self.run_discovery_quietly(
            timeout=120,
            json_report=report,
            start_directory=missing,
        )

        payload = self.load_report(report)
        self.assertEqual(code, 1)
        self.assertFalse(payload["success"])
        self.assertNotEqual(payload["returncode"], 0)

    def test_no_report_is_written_without_a_path(self) -> None:
        directory = self.make_fixture(_PASSING_FIXTURE)
        before = set(os.listdir(directory))

        code, _stdout, _stderr = self.run_discovery_quietly(
            timeout=120,
            start_directory=directory,
        )

        self.assertEqual(code, 0)
        self.assertEqual(set(os.listdir(directory)) - before, {"__pycache__"})


class TestDiscoveryRunnerEndToEnd(_DiscoveryFixtureMixin):
    def test_run_script_decodes_utf8_independently_of_host_locale(self) -> None:
        directory = self.make_fixture(_UTF8_OUTPUT_FIXTURE)

        try:
            with (
                patch.object(locale, "getencoding", return_value="ascii"),
                patch.dict(os.environ, {"PYTHONIOENCODING": "utf-8"}),
            ):
                completed, _elapsed = self.run_script(
                    ["--timeout", "120", "--start-directory", directory]
                )
        except UnicodeDecodeError as exc:
            self.fail(f"run_script used the host locale decoder: {exc}")

        self.assertEqual(completed.returncode, 0)
        self.assertIsInstance(completed.stderr, str)
        self.assertIn("Pound sign: £.", completed.stderr)

    def test_run_script_preserves_undecodable_output_as_byte_escapes(self) -> None:
        directory = self.make_fixture(_INVALID_UTF8_OUTPUT_FIXTURE)

        with patch.object(locale, "getencoding", return_value="utf-8"):
            completed, _elapsed = self.run_script(
                ["--timeout", "120", "--start-directory", directory]
            )

        self.assertEqual(completed.returncode, 0)
        self.assertIsInstance(completed.stdout, str)
        self.assertIn(r"invalid:\xff", completed.stdout)

    def test_passing_discovery_reports_success(self) -> None:
        directory = self.make_fixture(_PASSING_FIXTURE)
        report = self.report_path()

        completed, _elapsed = self.run_script(
            ["--timeout", "120", "--start-directory", directory, "--json-report", report]
        )

        payload = self.load_report(report)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(payload["success"])
        self.assertFalse(payload["timeout_expired"])
        self.assertEqual(payload["tests_reported"], 2)
        self.assertEqual(payload["ran_tests"], 2)
        self.assertEqual(payload["outcome"], "OK")
        self.assertEqual(payload["in_flight_test"], "")

    def test_failing_discovery_propagates_a_non_zero_exit(self) -> None:
        directory = self.make_fixture(_FAILING_FIXTURE)
        report = self.report_path()

        completed, _elapsed = self.run_script(
            ["--timeout", "120", "--start-directory", directory, "--json-report", report]
        )

        payload = self.load_report(report)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(payload["success"])
        self.assertFalse(payload["timeout_expired"])
        self.assertEqual(payload["tests_reported"], 1)

    def test_timeout_reclaims_grandchild_processes(self) -> None:
        directory = self.make_fixture(_GRANDCHILD_FIXTURE)
        Path(directory, "grandchild.py").write_text(
            _GRANDCHILD_SCRIPT, encoding="utf-8"
        )
        report = self.report_path()
        beat = Path(directory, "beat.txt")

        completed, _elapsed = self.run_script(
            ["--timeout", "3", "--start-directory", directory, "--json-report", report]
        )

        payload = self.load_report(report)
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(payload["timeout_expired"])
        # The wedged case leaves a detached grandchild behind. Killing only the
        # direct child leaves it writing, so the heartbeat must stop growing.
        self.assertTrue(beat.exists(), "grandchild never started")
        at_exit = beat.stat().st_size
        time.sleep(1.5)
        after = beat.stat().st_size
        self.assertLessEqual(
            after - at_exit,
            1,
            f"grandchild survived the deadline: {at_exit} -> {after} bytes",
        )

    def test_timeout_abandons_the_run_and_names_the_hung_test(self) -> None:
        directory = self.make_fixture(_HANGING_FIXTURE)
        report = self.report_path()

        completed, elapsed = self.run_script(
            ["--timeout", "2", "--start-directory", directory, "--json-report", report]
        )

        payload = self.load_report(report)
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(payload["timeout_expired"])
        self.assertFalse(payload["success"])
        # The wedged case sleeps for 30s; the deadline must cut the run short
        # instead of waiting for the test to finish.
        self.assertLess(elapsed, 20)
        self.assertIn("test_hangs", payload["in_flight_test"])
        self.assertIn("Hung test:", completed.stdout)
        self.assertEqual(payload["tests_reported"], 1)


if __name__ == "__main__":
    unittest.main()
