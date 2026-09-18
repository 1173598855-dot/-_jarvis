"""Durable directory contract tests - shared parent-directory flush primitive.

Run: python tests/test_durable_directory.py
"""
import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts import durable_directory
from core.contracts.durable_directory import (
    UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS,
    fsync_directory,
    supports_directory_fsync,
)


class TestSupportsDirectoryFsync(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows has no directory descriptor")
    def test_windows_is_unsupported(self):
        self.assertFalse(supports_directory_fsync())

    @unittest.skipIf(os.name == "nt", "POSIX exposes O_DIRECTORY")
    def test_posix_is_supported(self):
        self.assertTrue(supports_directory_fsync())

    def test_missing_o_directory_is_unsupported(self):
        with patch.object(durable_directory, "os") as fake_os:
            fake_os.name = "posix"
            del fake_os.O_DIRECTORY
            self.assertFalse(supports_directory_fsync())


class TestFsyncDirectory(unittest.TestCase):
    def test_unsupported_platform_never_opens_a_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                durable_directory,
                "supports_directory_fsync",
                return_value=False,
            ), patch.object(
                durable_directory.os,
                "open",
                side_effect=AssertionError("must not open a directory"),
            ):
                fsync_directory(Path(tmp))

    def test_open_tolerates_unsupported_filesystem_errnos(self):
        with tempfile.TemporaryDirectory() as tmp:
            for candidate in sorted(UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS):
                with self.subTest(errno=candidate):
                    with patch.object(
                        durable_directory,
                        "supports_directory_fsync",
                        return_value=True,
                    ), patch.object(
                        durable_directory.os,
                        "open",
                        side_effect=OSError(candidate, "not supported"),
                    ):
                        fsync_directory(Path(tmp))

    def test_open_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                durable_directory,
                "supports_directory_fsync",
                return_value=True,
            ), patch.object(
                durable_directory.os,
                "open",
                side_effect=OSError(errno.EACCES, "denied"),
            ):
                with self.assertRaises(OSError) as captured:
                    fsync_directory(Path(tmp))

            self.assertEqual(captured.exception.errno, errno.EACCES)

    def test_fsync_tolerates_unsupported_filesystem_errnos(self):
        with tempfile.TemporaryDirectory() as tmp:
            for candidate in sorted(UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS):
                with self.subTest(errno=candidate):
                    closed = []
                    with patch.object(
                        durable_directory,
                        "supports_directory_fsync",
                        return_value=True,
                    ), patch.object(
                        durable_directory.os,
                        "open",
                        return_value=4321,
                    ), patch.object(
                        durable_directory.os,
                        "fsync",
                        side_effect=OSError(candidate, "not supported"),
                    ), patch.object(
                        durable_directory.os,
                        "close",
                        side_effect=closed.append,
                    ):
                        fsync_directory(Path(tmp))

                    self.assertEqual(closed, [4321])

    def test_fsync_failure_fails_closed_and_closes_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            closed = []

            with patch.object(
                durable_directory,
                "supports_directory_fsync",
                return_value=True,
            ), patch.object(
                durable_directory.os,
                "open",
                return_value=4321,
            ), patch.object(
                durable_directory.os,
                "fsync",
                side_effect=OSError(errno.EIO, "device failure"),
            ), patch.object(
                durable_directory.os,
                "close",
                side_effect=closed.append,
            ):
                with self.assertRaises(OSError) as captured:
                    fsync_directory(Path(tmp))

            self.assertEqual(captured.exception.errno, errno.EIO)
            self.assertEqual(closed, [4321])

    def test_descriptor_is_closed_after_a_successful_flush(self):
        with tempfile.TemporaryDirectory() as tmp:
            closed = []

            with patch.object(
                durable_directory,
                "supports_directory_fsync",
                return_value=True,
            ), patch.object(
                durable_directory.os,
                "open",
                return_value=4321,
            ), patch.object(
                durable_directory.os,
                "fsync",
                return_value=None,
            ), patch.object(
                durable_directory.os,
                "close",
                side_effect=closed.append,
            ):
                fsync_directory(Path(tmp))

            self.assertEqual(closed, [4321])

    def test_open_uses_read_only_no_follow_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorded = []

            def record_open(path, flags):
                recorded.append((Path(path), flags))
                return 4321

            with patch.object(
                durable_directory,
                "supports_directory_fsync",
                return_value=True,
            ), patch.object(
                durable_directory.os,
                "open",
                side_effect=record_open,
            ), patch.object(
                durable_directory.os,
                "fsync",
                return_value=None,
            ), patch.object(
                durable_directory.os,
                "close",
                return_value=None,
            ):
                fsync_directory(Path(tmp))

            self.assertEqual(len(recorded), 1)
            path, flags = recorded[0]
            self.assertEqual(path, Path(tmp))
            self.assertTrue(flags & os.O_RDONLY == os.O_RDONLY)
            for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC"):
                expected = getattr(os, name, 0)
                if expected:
                    self.assertTrue(flags & expected, name)

    def test_accepts_string_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorded = []

            with patch.object(
                durable_directory,
                "supports_directory_fsync",
                return_value=True,
            ), patch.object(
                durable_directory.os,
                "open",
                side_effect=lambda path, flags: recorded.append(path) or 4321,
            ), patch.object(
                durable_directory.os,
                "fsync",
                return_value=None,
            ), patch.object(
                durable_directory.os,
                "close",
                return_value=None,
            ):
                fsync_directory(tmp)

            self.assertEqual(recorded, [tmp])

    @unittest.skipIf(os.name == "nt", "POSIX directory fsync behavior")
    def test_posix_flushes_a_real_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "entry.txt").write_text("payload", encoding="utf-8")
            fsync_directory(Path(tmp))


if __name__ == "__main__":
    unittest.main()
