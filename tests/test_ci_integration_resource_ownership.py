"""Port and log-directory ownership tests for the CI integration runner.

The runner previously bound a probe socket, closed it and returned the port
number, leaving the port unowned until the service bound it. These tests pin
the replacement contract: reservations stay bound, are distinct, are released
exactly where the child needs them, and never leak a socket on failure.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import socket
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
RUNNER = ROOT / "scripts" / "ci_local_integration.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("jarvis_ci_runner_ownership", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_bound(port: int) -> bool:
    """True when the port is already taken, i.e. a fresh bind is refused."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        return True
    finally:
        probe.close()
    return False


class TestPortReservationHoldsThePort(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_reserved_port_is_still_bound_before_release(self) -> None:
        reservation = self.runner._reserve_port()
        self.addCleanup(reservation.release)

        self.assertGreater(reservation.port, 0)
        self.assertTrue(_is_bound(reservation.port))

    def test_release_frees_the_port_for_the_child(self) -> None:
        reservation = self.runner._reserve_port()
        port = reservation.port
        reservation.release()

        self.assertFalse(_is_bound(port))

    def test_release_is_idempotent(self) -> None:
        reservation = self.runner._reserve_port()
        reservation.release()
        reservation.release()

        self.assertIsNone(reservation._socket)

    def test_reservation_refuses_a_reusing_bind(self) -> None:
        reservation = self.runner._reserve_port()
        self.addCleanup(reservation.release)

        stealer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stealer.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            with self.assertRaises(OSError):
                stealer.bind(("127.0.0.1", reservation.port))
        finally:
            stealer.close()

    def test_bind_failure_closes_the_socket_and_propagates(self) -> None:
        created: list = []
        real_socket = socket.socket

        def failing_socket(*args, **kwargs):
            sock = real_socket(*args, **kwargs)
            created.append(sock)
            return sock

        with patch.object(socket.socket, "bind", side_effect=OSError("no bind")):
            with patch.object(self.runner.socket, "socket", failing_socket):
                with self.assertRaises(OSError):
                    self.runner._reserve_port()

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].fileno(), -1)


class TestReservedPortsAreDistinct(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_three_reservations_are_held_simultaneously_and_distinct(self) -> None:
        reservations = self.runner._reserve_ports(3)
        for reservation in reservations:
            self.addCleanup(reservation.release)

        ports = [reservation.port for reservation in reservations]
        self.assertEqual(len(set(ports)), 3)
        for port in ports:
            self.assertTrue(_is_bound(port))

    def test_duplicate_ports_fail_closed_and_release_every_socket(self) -> None:
        reservations: list = []
        real_reserve = self.runner._reserve_port

        def duplicate_reserve():
            reservation = real_reserve()
            reservations.append(reservation)
            reservation.port = 45001
            return reservation

        with patch.object(self.runner, "_reserve_port", duplicate_reserve):
            with self.assertRaises(RuntimeError) as raised:
                self.runner._reserve_ports(3)

        self.assertIn("distinct loopback ports", str(raised.exception))
        self.assertEqual(len(reservations), 3)
        for reservation in reservations:
            self.assertIsNone(reservation._socket)

    def test_failure_midway_releases_the_earlier_reservations(self) -> None:
        reservations: list = []
        calls = {"count": 0}
        real_reserve = self.runner._reserve_port

        def flaky_reserve():
            calls["count"] += 1
            if calls["count"] == 3:
                raise OSError("exhausted")
            reservation = real_reserve()
            reservations.append(reservation)
            return reservation

        with patch.object(self.runner, "_reserve_port", flaky_reserve):
            with self.assertRaises(OSError):
                self.runner._reserve_ports(3)

        self.assertEqual(len(reservations), 2)
        for reservation in reservations:
            self.assertIsNone(reservation._socket)
            self.assertFalse(_is_bound(reservation.port))


class TestRunnerReleasesBeforeEachChild(unittest.TestCase):
    """The runner must free each port exactly where its service binds it."""

    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_each_reservation_is_released_before_its_service_starts(self) -> None:
        events: list = []

        class _Recording:
            def __init__(self, name: str, port: int) -> None:
                self.name = name
                self.port = port
                self._socket = object()

            def release(self) -> None:
                if self._socket is not None:
                    events.append(f"release:{self.name}")
                self._socket = None

        recorded = [
            _Recording("core", 45101),
            _Recording("ollama", 45102),
            _Recording("express", 45103),
        ]

        def fake_reserve_ports(count):
            self.assertEqual(count, 3)
            return list(recorded)

        class _FakeProcess:
            pid = None

            def poll(self):
                return None

            def wait(self, timeout=None):
                del timeout
                return 0

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                return None

        ports = {str(item.port): item.name for item in recorded}

        def fake_popen(command, **kwargs):
            env = kwargs.get("env") or {}
            # Name the child by the port it is about to bind, so the recorded
            # order proves each release happened before its own service start.
            candidates = [*map(str, command), str(env.get("PORT", ""))]
            bound = next(
                (ports[part] for part in candidates if part in ports),
                "unknown",
            )
            events.append(f"start:{bound}")
            return _FakeProcess()

        with patch.object(self.runner, "_reserve_ports", fake_reserve_ports), patch.object(
            self.runner.subprocess, "Popen", fake_popen
        ), patch.object(self.runner, "_wait_for_health", lambda *a, **k: None), patch.object(
            self.runner, "_run_profile", lambda **kwargs: 0
        ), patch.object(self.runner, "_stop", lambda process: None):
            self.assertEqual(self.runner.run_integration(timeout=1), 0)

        self.assertEqual(
            events,
            [
                "release:ollama",
                "start:ollama",
                "release:core",
                "start:core",
                "release:express",
                "start:express",
            ],
        )

    def test_unstarted_reservations_are_released_when_startup_fails(self) -> None:
        reservations = self.runner._reserve_ports(3)
        ports = [reservation.port for reservation in reservations]

        with patch.object(self.runner, "_reserve_ports", lambda count: reservations):
            with patch.object(
                self.runner.subprocess, "Popen", side_effect=OSError("cannot spawn")
            ):
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(self.runner.run_integration(timeout=1), 2)

        for reservation in reservations:
            self.assertIsNone(reservation._socket)
        for port in ports:
            self.assertFalse(_is_bound(port))

    def test_required_services_mode_is_validated_before_reserving(self) -> None:
        with patch.object(
            self.runner, "_reserve_ports", side_effect=AssertionError("reserved too early")
        ):
            with self.assertRaises(ValueError):
                self.runner.run_integration(require_services=False)


class TestLogDirectoryCleanupNeverMasksTheResult(unittest.TestCase):
    """A lingering log handle must not turn a passing profile into a failure."""

    def setUp(self) -> None:
        self.runner = _load_runner()

    def test_cleanup_removes_the_directory(self) -> None:
        log_dir = Path(tempfile.mkdtemp(prefix="jarvis-ci-cleanup-"))
        (log_dir / "core.log").write_bytes(b"x")

        self.runner._remove_log_dir(log_dir)

        self.assertFalse(log_dir.exists())

    def test_cleanup_retries_a_transient_windows_lock(self) -> None:
        log_dir = Path(tempfile.mkdtemp(prefix="jarvis-ci-cleanup-"))
        self.addCleanup(shutil.rmtree, log_dir, True)
        calls = {"count": 0}
        real_rmtree = shutil.rmtree

        def flaky_rmtree(path, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                raise OSError(32, "being used by another process")
            return real_rmtree(path, *args, **kwargs)

        with patch.object(self.runner.shutil, "rmtree", flaky_rmtree):
            with patch.object(self.runner.time, "sleep", lambda seconds: None):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.runner._remove_log_dir(log_dir)

        self.assertEqual(calls["count"], 3)
        self.assertNotIn("WARNING", stderr.getvalue())
        self.assertFalse(log_dir.exists())

    def test_cleanup_warns_instead_of_raising_when_it_never_succeeds(self) -> None:
        log_dir = Path(tempfile.mkdtemp(prefix="jarvis-ci-cleanup-"))
        self.addCleanup(shutil.rmtree, log_dir, True)

        with patch.object(
            self.runner.shutil, "rmtree", side_effect=OSError(32, "locked")
        ) as rmtree:
            with patch.object(self.runner.time, "sleep", lambda seconds: None):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.runner._remove_log_dir(log_dir)

        self.assertEqual(rmtree.call_count, self.runner._CLEANUP_ATTEMPTS)
        message = stderr.getvalue()
        self.assertIn("WARNING", message)
        self.assertIn(str(log_dir), message)

    def test_missing_directory_is_not_an_error(self) -> None:
        log_dir = Path(tempfile.mkdtemp(prefix="jarvis-ci-cleanup-"))
        shutil.rmtree(log_dir)

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.runner._remove_log_dir(log_dir)

        self.assertEqual(stderr.getvalue(), "")

    def test_passing_profile_survives_an_unremovable_log_directory(self) -> None:
        class _FakeProcess:
            pid = None

            def poll(self):
                return None

            def wait(self, timeout=None):
                del timeout
                return 0

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                return None

        with patch.object(
            self.runner.subprocess, "Popen", lambda command, **kwargs: _FakeProcess()
        ), patch.object(
            self.runner, "_wait_for_health", lambda *a, **k: None
        ), patch.object(
            self.runner, "_run_profile", lambda **kwargs: 0
        ), patch.object(
            self.runner, "_stop", lambda process: None
        ), patch.object(
            self.runner.shutil, "rmtree", side_effect=OSError(32, "locked")
        ), patch.object(
            self.runner.time, "sleep", lambda seconds: None
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = self.runner.run_integration(timeout=1)

        self.assertEqual(exit_code, 0)
        self.assertIn("WARNING", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
