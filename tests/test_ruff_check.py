"""Bounded child-process output tests for the local Ruff quality helper."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ruff_check


class _FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes, *, returncode: int = 0) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.kill_calls = 0
        self._running = returncode is None

    def poll(self) -> int | None:
        return None if self._running else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self._running = False
        return self.returncode or 0

    def kill(self) -> None:
        self.kill_calls += 1
        self._running = False


class TestRuffCheckOutputLimits(unittest.TestCase):
    def test_run_ruff_command_preserves_bounded_successful_output(self) -> None:
        process = _FakeProcess(b"lint output", b"format warning")
        with patch.object(ruff_check.subprocess, "Popen", return_value=process):
            result = ruff_check.run_ruff_command(["check"], Path("."))

        self.assertEqual(result, (0, "lint output", "format warning"))
        self.assertEqual(process.kill_calls, 0)

    def test_run_ruff_command_kills_child_on_stdout_overflow(self) -> None:
        process = _FakeProcess(b"123456789", b"", returncode=None)
        with (
            patch.object(ruff_check, "_MAX_RUFF_OUTPUT_BYTES", 8),
            patch.object(ruff_check, "_RUFF_READ_CHUNK_BYTES", 4),
            patch.object(ruff_check.subprocess, "Popen", return_value=process),
        ):
            result = ruff_check.run_ruff_command(["check"], Path("."))

        self.assertEqual(result[0], -1)
        self.assertEqual(result[1], "")
        self.assertIn("ruff output exceeds 8 bytes", result[2])
        self.assertEqual(process.kill_calls, 1)

    def test_run_ruff_command_kills_child_on_stderr_overflow(self) -> None:
        process = _FakeProcess(b"", b"123456789", returncode=None)
        with (
            patch.object(ruff_check, "_MAX_RUFF_OUTPUT_BYTES", 8),
            patch.object(ruff_check, "_RUFF_READ_CHUNK_BYTES", 4),
            patch.object(ruff_check.subprocess, "Popen", return_value=process),
        ):
            result = ruff_check.run_ruff_command(["format"], Path("."))

        self.assertEqual(result[0], -1)
        self.assertEqual(result[1], "")
        self.assertIn("ruff output exceeds 8 bytes", result[2])
        self.assertEqual(process.kill_calls, 1)

    def test_check_ruff_installed_rejects_oversized_version_output(self) -> None:
        process = _FakeProcess(b"v" * 9, b"", returncode=None)
        with (
            patch.object(ruff_check, "_MAX_RUFF_OUTPUT_BYTES", 8),
            patch.object(ruff_check, "_RUFF_READ_CHUNK_BYTES", 4),
            patch.object(ruff_check.shutil, "which", return_value="ruff"),
            patch.object(ruff_check.subprocess, "Popen", return_value=process),
        ):
            version = ruff_check.check_ruff_installed()

        self.assertIsNone(version)
        self.assertEqual(process.kill_calls, 1)

    def test_check_ruff_installed_falls_back_to_current_python_module(self) -> None:
        process = _FakeProcess(b"ruff 0.16.2\n", b"")
        with (
            patch.object(ruff_check.shutil, "which", return_value=None),
            patch.object(ruff_check.sys, "executable", "python-test"),
            patch.object(ruff_check.subprocess, "Popen", return_value=process) as popen,
        ):
            version = ruff_check.check_ruff_installed()

        self.assertEqual(version, "ruff 0.16.2")
        self.assertEqual(
            popen.call_args.args[0],
            ["python-test", "-m", "ruff", "--version"],
        )


if __name__ == "__main__":
    unittest.main()
