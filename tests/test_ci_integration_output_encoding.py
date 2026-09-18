"""Service-output decoding tests for the CI integration runner.

The failure log tail exists to explain why a service died. Decoding it as UTF-8
unconditionally turned a real Windows socket error into replacement characters,
so these tests pin the decoding contract and the child environment that keeps
Python services emitting UTF-8 in the first place.
"""

from __future__ import annotations

import importlib.util
import io
import locale
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
RUNNER = ROOT / "scripts" / "ci_local_integration.py"

# "PermissionError: [WinError 10013] ..." as emitted by a Chinese-locale host.
_WINDOWS_SOCKET_ERROR = (
    "PermissionError: [WinError 10013] "
    "以一种访问权限不允许的方式做了一个访问套接字的尝试。"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("jarvis_ci_runner_encoding", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gbk_available() -> bool:
    try:
        _WINDOWS_SOCKET_ERROR.encode("gbk")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


class _RecordingProcess:
    pid = None

    def __init__(self) -> None:
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self) -> None:
        self._returncode = -15

    def wait(self, timeout=None):
        del timeout
        if self._returncode is None:
            self._returncode = 0
        return self._returncode

    def kill(self) -> None:
        self._returncode = -9


class TestServiceOutputDecoding(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_utf8_output_is_decoded_exactly(self) -> None:
        text = "core ready 就绪"

        self.assertEqual(
            self.runner._decode_service_output(text.encode("utf-8")), text
        )

    def test_ascii_output_is_unchanged(self) -> None:
        self.assertEqual(
            self.runner._decode_service_output(b"EADDRINUSE 127.0.0.1:9999"),
            "EADDRINUSE 127.0.0.1:9999",
        )

    @unittest.skipUnless(_gbk_available(), "GBK codec unavailable")
    def test_locale_encoded_output_is_recovered_not_mangled(self) -> None:
        data = _WINDOWS_SOCKET_ERROR.encode("gbk")
        # Guard the premise: these bytes are not valid UTF-8.
        with self.assertRaises(UnicodeDecodeError):
            data.decode("utf-8")

        with patch.object(locale, "getpreferredencoding", return_value="gbk"):
            decoded = self.runner._decode_service_output(data)

        self.assertIn("10013", decoded)
        self.assertIn("套接字", decoded)
        self.assertNotIn("\ufffd", decoded)

    def test_undecodable_output_still_returns_text(self) -> None:
        data = b"\xff\xfe\x00 broken"

        with patch.object(locale, "getpreferredencoding", return_value="ascii"):
            decoded = self.runner._decode_service_output(data)

        self.assertIsInstance(decoded, str)
        self.assertIn("broken", decoded)

    def test_unknown_locale_encoding_does_not_raise(self) -> None:
        with patch.object(locale, "getpreferredencoding", return_value="not-a-codec"):
            decoded = self.runner._decode_service_output(b"\xa1\xa2 tail")

        self.assertIn("tail", decoded)

    def test_locale_lookup_failure_falls_back_to_replacement(self) -> None:
        with patch.object(locale, "getpreferredencoding", side_effect=ValueError):
            decoded = self.runner._decode_service_output(b"\xa1\xa2 tail")

        self.assertIn("tail", decoded)


class TestFailureTailSurfacesRealErrors(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        self.directory = tempfile.mkdtemp(prefix="ci-encoding-")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    @unittest.skipUnless(_gbk_available(), "GBK codec unavailable")
    def test_reported_tail_contains_the_socket_error_text(self) -> None:
        log = Path(self.directory, "ollama-fixture.log")
        log.write_bytes(_WINDOWS_SOCKET_ERROR.encode("gbk"))
        service = self.runner._Service(
            "ollama-fixture", _RecordingProcess(), log
        )

        stderr = io.StringIO()
        with patch.object(locale, "getpreferredencoding", return_value="gbk"):
            with redirect_stderr(stderr):
                self.runner._report_service_logs([service])
        output = stderr.getvalue()

        self.assertIn("ollama-fixture", output)
        self.assertIn("10013", output)
        self.assertNotIn("\ufffd", output)

    @unittest.skipUnless(_gbk_available(), "GBK codec unavailable")
    def test_tail_of_a_real_child_writing_locale_bytes_is_readable(self) -> None:
        # Node and other non-Python services are not covered by
        # PYTHONIOENCODING, so the decoder must still handle their bytes.
        log = Path(self.directory, "express.log")
        script = (
            "import sys\n"
            f"sys.stdout.buffer.write({_WINDOWS_SOCKET_ERROR.encode('gbk')!r})\n"
        )
        with log.open("wb") as handle:
            child = subprocess.Popen(
                [sys.executable, "-c", script],
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            child.wait(timeout=60)

        with patch.object(locale, "getpreferredencoding", return_value="gbk"):
            tail = self.runner._read_log_tail(log)

        self.assertIn("10013", tail)
        self.assertNotIn("\ufffd", tail)

    def test_tail_stays_bounded_for_large_locale_encoded_logs(self) -> None:
        log = Path(self.directory, "core.log")
        log.write_bytes(b"A" * 20_000 + b"FINAL_LINE")

        tail = self.runner._read_log_tail(log)

        self.assertIn("FINAL_LINE", tail)
        self.assertLessEqual(len(tail.encode("utf-8")), self.runner._LOG_TAIL_BYTES)


class TestChildEnvironmentForcesUtf8(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_python_services_are_started_with_utf8_io(self) -> None:
        captured = []

        def recording_popen(command, **kwargs):
            captured.append(kwargs.get("env") or {})
            raise RuntimeError("stop after the first service start")

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.runner.subprocess, "Popen", recording_popen):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.runner.run_integration(timeout=1, overall_timeout=5)

        self.assertEqual(code, 2)
        self.assertTrue(captured, "no service was started")
        self.assertEqual(captured[0].get("PYTHONIOENCODING"), "utf-8")
        self.assertEqual(captured[0].get("PYTHONUNBUFFERED"), "1")


if __name__ == "__main__":
    unittest.main()
