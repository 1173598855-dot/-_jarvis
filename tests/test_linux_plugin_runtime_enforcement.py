"""Real Linux enforcement probe for the production Plugin Runtime chain."""

from __future__ import annotations

import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
RUN_REAL_ENFORCEMENT = (
    sys.platform.startswith("linux")
    and os.environ.get("JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT") == "1"
)
_DRIVER_TIMEOUT_SECONDS = 20
_DIAGNOSTIC_LIMIT = 8 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_PROC_CHILDREN_BYTES = 4 * 1024
_MAX_DIRECT_CHILDREN = 32
_RECLAIM_TIMEOUT_SECONDS = 2.0
_FORCE_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


def _read_bounded_probe_stream(
    stream: object,
    limit: int,
    chunks: list[bytes],
    overflow: threading.Event,
) -> None:
    total = 0
    try:
        while not overflow.is_set():
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                return
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            elif not isinstance(chunk, bytes):
                chunk = bytes(chunk)
            retained = chunk[: max(0, limit - total)]
            if retained:
                chunks.append(retained)
                total += len(retained)
            if len(retained) < len(chunk):
                overflow.set()
                return
    except (OSError, TypeError, ValueError):
        overflow.set()


def _collect_bounded_probe_output(
    process: object,
    *,
    timeout: float,
    stream_limit: int,
    abort,
) -> tuple[bytes, bytes, bool, bool]:
    """Drain a probe without retaining more than the fixed per-stream limit."""
    stdout_stream = getattr(process, "stdout", None)
    stderr_stream = getattr(process, "stderr", None)
    if not callable(getattr(stdout_stream, "read", None)) or not callable(
        getattr(stderr_stream, "read", None)
    ):
        abort()
        raise RuntimeError("probe streams are unavailable")

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    overflow = threading.Event()
    readers = (
        threading.Thread(
            target=_read_bounded_probe_stream,
            args=(stdout_stream, stream_limit, stdout_chunks, overflow),
            daemon=True,
        ),
        threading.Thread(
            target=_read_bounded_probe_stream,
            args=(stderr_stream, stream_limit, stderr_chunks, overflow),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout
    timed_out = False
    aborted = False

    def abort_once() -> None:
        nonlocal aborted
        if aborted:
            return
        aborted = True
        abort()

    try:
        while True:
            if overflow.is_set():
                abort_once()
                break
            if process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                abort_once()
                break
            try:
                process.wait(timeout=min(remaining, 0.05))
            except subprocess.TimeoutExpired:
                continue

        if aborted:
            try:
                process.wait(timeout=_RECLAIM_TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass

        join_deadline = time.monotonic() + _RECLAIM_TIMEOUT_SECONDS
        for reader in readers:
            reader.join(timeout=max(0.0, join_deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            overflow.set()
            abort_once()
    except BaseException:
        abort_once()
        raise
    finally:
        for stream in (stdout_stream, stderr_stream):
            try:
                stream.close()
            except (OSError, AttributeError, ValueError):
                pass

    return (
        b"".join(stdout_chunks),
        b"".join(stderr_chunks),
        timed_out,
        overflow.is_set(),
    )


def _read_pid_tokens(path: Path, limit: int) -> tuple[int, ...]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(_PROC_CHILDREN_BYTES + 1)
    except OSError:
        return ()
    if len(raw) > _PROC_CHILDREN_BYTES:
        return ()
    try:
        tokens = raw.decode("ascii").split()
    except UnicodeDecodeError:
        return ()
    if len(tokens) > limit or any(not token.isascii() or not token.isdigit() for token in tokens):
        return ()
    return tuple(pid for token in tokens if (pid := int(token)) > 0)


def _probe_worker_pids(
    driver_pid: int,
    worker_pid_path: Path,
    proc_root: Path,
) -> tuple[int, ...]:
    candidates = set(_read_pid_tokens(worker_pid_path, 1))
    candidates.update(
        _read_pid_tokens(
            proc_root
            / str(driver_pid)
            / "task"
            / str(driver_pid)
            / "children",
            _MAX_DIRECT_CHILDREN,
        )
    )
    candidates.discard(driver_pid)
    return tuple(sorted(candidates))


def _process_group_is_empty(group: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _terminate_linux_probe_tree(
    process: object,
    *,
    worker_pid_path: Path,
    proc_root: Path = Path("/proc"),
    timeout: float = _RECLAIM_TIMEOUT_SECONDS,
) -> bool:
    """Terminate nested Worker groups before the outer driver group."""
    driver_pid = getattr(process, "pid", None)
    if not isinstance(driver_pid, int) or isinstance(driver_pid, bool) or driver_pid <= 0:
        return False

    groups: list[int] = []
    for pid in _probe_worker_pids(driver_pid, worker_pid_path, proc_root):
        try:
            group = os.getpgid(pid)
        except OSError:
            continue
        if group == pid:
            groups.append(group)

    try:
        driver_group = os.getpgid(driver_pid)
    except OSError:
        driver_group = None
    if driver_group == driver_pid:
        groups.append(driver_group)
    else:
        try:
            process.kill()
        except (OSError, AttributeError, ValueError):
            pass

    for group in groups:
        try:
            os.killpg(group, _FORCE_KILL_SIGNAL)
        except ProcessLookupError:
            continue
        except OSError:
            if group == driver_pid:
                try:
                    process.kill()
                except (OSError, AttributeError, ValueError):
                    pass

    try:
        process.wait(timeout=timeout)
        driver_exited = True
    except (OSError, subprocess.TimeoutExpired, ValueError):
        driver_exited = getattr(process, "poll", lambda: None)() is not None

    return driver_exited and all(
        _process_group_is_empty(group, timeout) for group in groups
    )


class _FakeProbeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"") -> None:
        self.pid = 101
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(["probe"], timeout)
        return self.returncode

    def kill(self) -> None:
        self.returncode = -_FORCE_KILL_SIGNAL


class TestLinuxPluginRuntimeProbeHarness(unittest.TestCase):
    def test_output_overflow_is_bounded_and_triggers_tree_abort(self) -> None:
        collector = globals().get("_collect_bounded_probe_output")
        self.assertIsNotNone(collector, "bounded probe collector is missing")
        process = _FakeProbeProcess(b"x" * 9, b"diagnostic")
        aborts = []

        def abort() -> None:
            aborts.append(process.pid)
            process.kill()

        stdout, _stderr, timed_out, output_limited = collector(
            process,
            timeout=1,
            stream_limit=8,
            abort=abort,
        )

        self.assertEqual(stdout, b"x" * 8)
        self.assertFalse(timed_out)
        self.assertTrue(output_limited)
        self.assertEqual(aborts, [process.pid])

    def test_tree_abort_kills_worker_groups_before_driver_and_confirms_exit(
        self,
    ) -> None:
        terminator = globals().get("_terminate_linux_probe_tree")
        self.assertIsNotNone(terminator, "Linux probe tree terminator is missing")
        process = _FakeProbeProcess(b"")

        with tempfile.TemporaryDirectory(prefix=".test-probe-proc-") as temporary:
            proc_root = Path(temporary)
            children = proc_root / str(process.pid) / "task" / str(process.pid)
            children.mkdir(parents=True)
            (children / "children").write_text("202 203", encoding="ascii")
            worker_pid = proc_root / "worker.pid"
            worker_pid.write_text("202", encoding="ascii")

            def kill_group(group: int, requested_signal: int) -> None:
                if requested_signal == 0:
                    raise ProcessLookupError(group)
                if group == process.pid:
                    process.returncode = -_FORCE_KILL_SIGNAL

            with (
                patch.object(os, "getpgid", side_effect=lambda pid: pid, create=True),
                patch.object(os, "killpg", side_effect=kill_group, create=True) as killpg,
            ):
                confirmed = terminator(
                    process,
                    worker_pid_path=worker_pid,
                    proc_root=proc_root,
                    timeout=1,
                )

        self.assertTrue(confirmed)
        self.assertEqual(
            [call.args for call in killpg.call_args_list[:3]],
            [
                (202, _FORCE_KILL_SIGNAL),
                (203, _FORCE_KILL_SIGNAL),
                (process.pid, _FORCE_KILL_SIGNAL),
            ],
        )

    def test_tree_abort_falls_back_when_driver_group_cannot_be_inspected(
        self,
    ) -> None:
        process = _FakeProbeProcess(b"")
        with tempfile.TemporaryDirectory(prefix=".test-probe-proc-") as temporary:
            proc_root = Path(temporary)
            worker_pid = proc_root / "worker.pid"
            worker_pid.write_text("", encoding="ascii")
            with patch.object(
                os,
                "getpgid",
                side_effect=OSError("group unavailable"),
                create=True,
            ):
                confirmed = _terminate_linux_probe_tree(
                    process,
                    worker_pid_path=worker_pid,
                    proc_root=proc_root,
                    timeout=0,
                )

        self.assertTrue(confirmed)
        self.assertEqual(process.returncode, -_FORCE_KILL_SIGNAL)


@unittest.skipUnless(
    RUN_REAL_ENFORCEMENT,
    "requires an explicit real Linux Plugin Runtime isolation run",
)
class TestLinuxPluginRuntimeEnforcement(unittest.TestCase):
    def test_production_runtime_enforces_worker_boundary(self) -> None:
        payload = self._run_probe_driver_as_unprivileged_identity()

        self.assertEqual(
            payload["baseline"],
            {
                "gid": payload["probe_gid"],
                "loopback": "allowed",
                "outside_read": "allowed",
                "outside_write": "allowed",
                "plugin_root_write": "allowed",
                "uid": payload["probe_uid"],
            },
        )
        self.assertNotEqual(payload["baseline"]["uid"], 65_534)
        self.assertNotEqual(payload["baseline"]["gid"], 65_534)
        self.assertEqual(payload["driver_pid"], payload["outer_driver_pid"])
        self.assertGreater(payload["worker_pid"], 0)
        self.assertNotEqual(payload["driver_pid"], payload["worker_pid"])
        self.assertEqual(payload["lifecycle"], ["loaded", "enabled"])
        self.assertEqual(payload["lifecycle_success"], [True, True])
        self.assertEqual(payload["event_source"], "plugin:runtime-probe")

        restricted = dict(payload["restricted"])
        worker_path = Path(restricted.pop("worker_path"))
        self.assertEqual(
            restricted,
            {
                "loopback": "denied",
                "outside_read": "denied",
                "outside_write": "denied",
                "plugin_root_write": "denied",
                "worker_write": "allowed",
            },
        )
        self.assertEqual(worker_path.name, "runtime-probe.txt")
        self.assertTrue(worker_path.parent.name.startswith("jarvis-plugin-worker-"))
        self.assertEqual(payload["outside_content"], "baseline")
        self.assertEqual(payload["outer_outside_content"], "baseline")
        self.assertEqual(payload["outer_plugin_marker_content"], "baseline")
        self.assertTrue(payload["worker_exists_before_close"])
        self.assertTrue(payload["termination_confirmed"])
        self.assertFalse(payload["worker_alive_after_close"])
        self.assertTrue(payload["worker_root_reclaimed"])

    def _run_probe_driver_as_unprivileged_identity(self) -> dict:
        with tempfile.TemporaryDirectory(
            prefix=".test-linux-plugin-runtime-enforcement-"
        ) as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_text("baseline", encoding="utf-8")
            plugin_root = root / "runtime-probe"
            plugin_root.mkdir()
            plugin_marker = plugin_root / "read-only-marker.txt"
            plugin_marker.write_text("baseline", encoding="utf-8")
            source_root = root / "probe-source"
            source_root.mkdir()
            worker_pid_path = root / "worker.pid"
            worker_pid_path.write_text("", encoding="ascii")

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            try:
                plugin = plugin_root / "plugin.py"
                plugin.write_text(
                    self._plugin_source(
                        outside,
                        plugin_marker,
                        listener.getsockname()[1],
                    ),
                    encoding="utf-8",
                )
                driver = source_root / "probe_driver.py"
                driver.write_text(self._driver_source(), encoding="utf-8")

                root.chmod(0o755)
                outside.chmod(0o666)
                plugin_root.chmod(0o755)
                plugin_marker.chmod(0o666)
                plugin.chmod(0o644)
                source_root.chmod(0o755)
                driver.chmod(0o644)
                worker_pid_path.chmod(0o666)

                probe_uid = os.geteuid()
                probe_gid = os.getegid()
                demote = None
                if probe_uid == 0:
                    probe_uid = 12_345
                    probe_gid = 12_345

                    def demote() -> None:
                        os.setgroups([])
                        os.setgid(probe_gid)
                        os.setuid(probe_uid)

                environment = {
                    "PATH": os.environ.get("PATH", os.defpath),
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONPATH": str(ROOT / "src"),
                    "PYTHONUNBUFFERED": "1",
                    "PROBE_OUTSIDE": str(outside),
                    "PROBE_PLUGIN_MARKER": str(plugin_marker),
                    "PROBE_PLUGIN_ROOT": str(plugin_root),
                    "PROBE_PORT": str(listener.getsockname()[1]),
                    "PROBE_WORKER_PID": str(worker_pid_path),
                }
                process = subprocess.Popen(
                    [sys.executable, "-S", "-u", str(driver)],
                    cwd=source_root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=demote,
                    start_new_session=True,
                )
                abort_called = False
                cleanup_confirmed = True

                def abort() -> None:
                    nonlocal abort_called, cleanup_confirmed
                    if abort_called:
                        return
                    abort_called = True
                    cleanup_confirmed = _terminate_linux_probe_tree(
                        process,
                        worker_pid_path=worker_pid_path,
                    )

                try:
                    stdout, stderr, timed_out, output_limited = (
                        _collect_bounded_probe_output(
                            process,
                            timeout=_DRIVER_TIMEOUT_SECONDS,
                            stream_limit=_DIAGNOSTIC_LIMIT,
                            abort=abort,
                        )
                    )
                    diagnostic = stderr.decode("utf-8", errors="replace")
                    if timed_out:
                        self.fail(
                            "Linux Plugin Runtime probe exceeded its "
                            f"{_DRIVER_TIMEOUT_SECONDS}-second deadline "
                            f"(cleanup_confirmed={cleanup_confirmed}): "
                            + diagnostic
                        )
                    if output_limited:
                        self.fail(
                            "Linux Plugin Runtime probe output exceeded its "
                            f"{_DIAGNOSTIC_LIMIT}-byte per-stream limit "
                            f"(cleanup_confirmed={cleanup_confirmed})"
                        )
                    if process.returncode != 0:
                        abort()
                        self.fail(
                            f"probe exited {process.returncode} "
                            f"(cleanup_confirmed={cleanup_confirmed}): {diagnostic}"
                        )
                except BaseException:
                    abort()
                    raise
                try:
                    payload = json.loads(stdout.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    abort()
                    self.fail(
                        "probe did not return one UTF-8 JSON document: "
                        + stderr.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )
                payload["outer_driver_pid"] = process.pid
                payload["outer_outside_content"] = outside.read_text(encoding="utf-8")
                payload["outer_plugin_marker_content"] = plugin_marker.read_text(
                    encoding="utf-8"
                )
                payload["probe_uid"] = probe_uid
                payload["probe_gid"] = probe_gid
                return payload
            finally:
                listener.close()

    @staticmethod
    def _plugin_source(outside: Path, plugin_marker: Path, port: int) -> str:
        return textwrap.dedent(
            f"""
            import socket
            import tempfile
            from pathlib import Path

            OUTSIDE = Path({str(outside)!r})
            PLUGIN_MARKER = Path({str(plugin_marker)!r})
            PORT = {port}


            def _attempt(operation):
                try:
                    operation()
                except OSError:
                    return "denied"
                return "allowed"


            def _connect_loopback():
                with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                    pass


            def activate(api):
                worker_path = Path(tempfile.gettempdir()) / "runtime-probe.txt"
                result = {{
                    "outside_read": _attempt(
                        lambda: OUTSIDE.read_text(encoding="utf-8")
                    ),
                    "outside_write": _attempt(
                        lambda: OUTSIDE.write_text("forbidden", encoding="utf-8")
                    ),
                    "plugin_root_write": _attempt(
                        lambda: PLUGIN_MARKER.write_text(
                            "forbidden", encoding="utf-8"
                        )
                    ),
                    "loopback": _attempt(_connect_loopback),
                    "worker_write": _attempt(
                        lambda: worker_path.write_text("allowed", encoding="utf-8")
                    ),
                    "worker_path": str(worker_path),
                }}
                api.emit_event("plugin.linux_runtime_probe", result)
            """
        ).lstrip()

    @staticmethod
    def _driver_source() -> str:
        return textwrap.dedent(
            """
            import json
            import os
            import socket
            from pathlib import Path

            from adapters.subprocess_plugin_runtime import (
                PluginWorkerTimeouts,
                SubprocessPluginRuntime,
            )
            from core.contracts.plugin_worker_protocol import (
                LifecycleAction,
                PluginLoadSpec,
            )
            from core.kernel.event_bus import EventBus
            from core.kernel.plugin_broker import PluginBroker


            def attempt(operation):
                try:
                    operation()
                except OSError:
                    return "denied"
                return "allowed"


            def connect_loopback(port):
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    pass


            outside = Path(os.environ["PROBE_OUTSIDE"])
            plugin_marker = Path(os.environ["PROBE_PLUGIN_MARKER"])
            plugin_root = Path(os.environ["PROBE_PLUGIN_ROOT"])
            port = int(os.environ["PROBE_PORT"])
            worker_pid_path = Path(os.environ["PROBE_WORKER_PID"])
            baseline = {
                "uid": os.geteuid(),
                "gid": os.getegid(),
                "outside_read": attempt(
                    lambda: outside.read_text(encoding="utf-8")
                ),
                "outside_write": attempt(
                    lambda: outside.write_text("baseline", encoding="utf-8")
                ),
                "plugin_root_write": attempt(
                    lambda: plugin_marker.write_text(
                        "baseline", encoding="utf-8"
                    )
                ),
                "loopback": attempt(lambda: connect_loopback(port)),
            }

            bus = EventBus()
            runtime = None
            worker_path = None
            try:
                broker = PluginBroker(
                    bus,
                    grants={plugin_root.name: {"event.emit"}},
                )
                broker.register_event_emit_handler()
                runtime = SubprocessPluginRuntime(
                    plugin_root,
                    PluginLoadSpec("plugin.py", ("event_bus",), "1.0.0", 1),
                    broker,
                    timeouts=PluginWorkerTimeouts(
                        handshake=5,
                        load=5,
                        activate=5,
                        deactivate=5,
                        cleanup=5,
                        shutdown=5,
                        terminate=1,
                        kill=1,
                    ),
                )
                snapshot = runtime.start()
                worker_pid_path.write_text(str(snapshot.pid), encoding="ascii")
                loaded = runtime.invoke(LifecycleAction.LOAD)
                activated = runtime.invoke(LifecycleAction.ACTIVATE)
                events = bus.get_history("plugin.linux_runtime_probe", limit=2)
                if len(events) != 1:
                    audit = [
                        {
                            "capability": entry.capability,
                            "allowed": entry.allowed,
                            "reason": entry.reason,
                        }
                        for entry in broker.audit_log()
                    ]
                    raise RuntimeError(
                        "expected exactly one committed probe event: "
                        + json.dumps(
                            {
                                "loaded": loaded.to_dict(),
                                "activated": activated.to_dict(),
                                "broker_audit": audit,
                            },
                            sort_keys=True,
                        )
                    )
                event = events[0]
                restricted = dict(event.payload)
                worker_path = Path(restricted["worker_path"])
                worker_exists_before_close = worker_path.is_file()
            finally:
                try:
                    if runtime is not None:
                        runtime.close()
                finally:
                    bus.destroy()

            if worker_path is None:
                raise RuntimeError("probe event did not provide a Worker path")
            result = {
                "baseline": baseline,
                "driver_pid": os.getpid(),
                "worker_pid": snapshot.pid,
                "lifecycle": [loaded.status, activated.status],
                "lifecycle_success": [loaded.success, activated.success],
                "event_source": event.source,
                "restricted": restricted,
                "outside_content": outside.read_text(encoding="utf-8"),
                "worker_exists_before_close": worker_exists_before_close,
                "termination_confirmed": runtime.snapshot.termination_confirmed,
                "worker_alive_after_close": runtime.process_is_alive(),
                "worker_root_reclaimed": not worker_path.parent.exists(),
            }
            print(json.dumps(result, sort_keys=True), flush=True)
            """
        ).lstrip()


if __name__ == "__main__":
    unittest.main()
