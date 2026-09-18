"""Tests for the parent-owned subprocess plugin runtime."""

from __future__ import annotations

import io
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adapters.subprocess_plugin_runtime import (
    PluginRuntimeError,
    PluginWorkerTimeouts,
    SubprocessPluginRuntime,
)
from core.contracts.plugin_worker_protocol import (
    MAX_PLUGIN_WORKER_LINE_BYTES,
    LifecycleAction,
    PluginLifecycleRequest,
    PluginLifecycleResult,
    PluginLoadSpec,
    PluginWorkerHello,
    decode_message,
    encode_message,
)
from core.kernel.event_bus import EventBus
from core.kernel.plugin_broker import MAX_BROKER_CALLS, PluginBroker
from core.kernel.process_containment import ProcessContainmentError
from tests.plugin_network_fixture import NetworkFixtureServer

PLUGIN_ID = "fixture-plugin"


class _BlockingReader:
    def __init__(self) -> None:
        self._closed = threading.Event()

    def readline(self, _limit: int = -1) -> bytes:
        self._closed.wait(2)
        return b""

    def close(self) -> None:
        self._closed.set()


class _HandshakeTimeoutProcess:
    def __init__(self) -> None:
        self.pid = 43210
        self.stdin = io.BytesIO()
        self.stdout = _BlockingReader()
        self.stderr = io.BytesIO()
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("worker", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 15

    def kill(self) -> None:
        self.returncode = 9


class _UnreapableProcess:
    def __init__(self) -> None:
        self.pid = 43211
        self.stdin = io.BytesIO()
        self.stdout = _GatedIdleStdout(self.pid, "eof")
        self.stderr = io.BytesIO()
        self.actions: list[str] = []
        self.released = False

    def poll(self):
        return 0 if self.released else None

    def wait(self, timeout=None):
        self.actions.append("wait")
        if self.released:
            return 0
        raise subprocess.TimeoutExpired("worker", timeout)

    def terminate(self) -> None:
        self.actions.append("terminate")

    def kill(self) -> None:
        self.actions.append("kill")


class _FlakyWorkerTemp:
    def __init__(self) -> None:
        self.calls = 0

    def cleanup(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise OSError("temporary cleanup is busy")


class _ControlledContainment:
    def __init__(self) -> None:
        self.empty = False
        self.close_calls = 0
        self.is_attached = True

    def terminate(self, *, force: bool) -> bool:
        return True

    def wait_empty(self, _timeout: float) -> bool:
        return self.empty

    def close(self) -> bool:
        self.close_calls += 1
        return True


class _SuccessfulWorkerTemp:
    def __init__(self) -> None:
        self.calls = 0

    def cleanup(self) -> None:
        self.calls += 1


class _TrackingContainer:
    interpreter = Path("python.exe")
    writable_root = Path("worker-temp")

    def __init__(self) -> None:
        self.close_calls = 0
        self.spawn_calls = 0

    def stage(self, _source: Path, name: str) -> Path:
        return Path("staged") / name

    def spawn(self, *_arguments, **_keywords):
        self.spawn_calls += 1
        raise AssertionError("container spawn must not run after staged validation fails")

    def close(self) -> None:
        self.close_calls += 1


class _TrackingMacOSSandbox:
    writable_root = Path("macos-worker-temp")

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _FailingMacOSSandbox(_TrackingMacOSSandbox):
    def stage(self, _source: Path, _name: str) -> Path:
        from core.kernel.worker_macos_sandbox import WorkerMacOSSandboxError

        raise WorkerMacOSSandboxError("macOS staging failed")


class _GatedIdleStdout:
    def __init__(
        self, pid: int, fault: str, gate: threading.Event | None = None
    ) -> None:
        self._hello = encode_message(PluginWorkerHello(f"worker-{pid}", pid))
        self._fault = fault
        self._hello_sent = False
        self._gate = gate or threading.Event()
        self._closed = threading.Event()

    def trigger(self) -> None:
        self._gate.set()

    def readline(self, _limit: int = -1) -> bytes:
        if not self._hello_sent:
            self._hello_sent = True
            return self._hello
        self._gate.wait(2)
        if self._closed.is_set() or self._fault == "eof":
            return b""
        if self._fault == "reader_error":
            raise OSError("controlled post-hello reader failure")
        if self._fault == "oversized":
            return b"x" * (MAX_PLUGIN_WORKER_LINE_BYTES + 1)
        return self._hello

    def close(self) -> None:
        self._closed.set()
        self._gate.set()


class _IdleFaultProcess:
    def __init__(self, fault: str, gate: threading.Event | None = None) -> None:
        self.pid = 43212
        self.stdin = io.BytesIO()
        self.stdout = _GatedIdleStdout(self.pid, fault, gate)
        self.stderr = io.BytesIO()
        self.returncode = None
        self.actions: list[str] = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.actions.append("wait")
        if self.returncode is None:
            raise subprocess.TimeoutExpired("worker", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.actions.append("terminate")
        self.returncode = 15

    def kill(self) -> None:
        self.actions.append("kill")
        self.returncode = 9


class _PreHelloFaultStdout:
    def __init__(self, fault: str) -> None:
        self._fault = fault
        self._closed = False

    def readline(self, _limit: int = -1) -> bytes:
        if self._fault == "reader_error":
            raise OSError("controlled pre-hello reader failure")
        return b""

    def close(self) -> None:
        self._closed = True


class _FaultBeforeGetQueue(queue.Queue):
    def __init__(self, fault_ready: threading.Event, maxsize: int = 64) -> None:
        super().__init__(maxsize=maxsize)
        self._fault_ready = fault_ready
        self.consumer_waiting = threading.Event()

    def put_nowait(self, item) -> None:
        super().put_nowait(item)
        if item[0] in {"eof", "overflow", "reader_error"}:
            self._fault_ready.set()

    def get(self, block=True, timeout=None):
        self.consumer_waiting.set()
        self._fault_ready.wait(2)
        return super().get(block=block, timeout=timeout)


class _ShutdownOrderingQueue(queue.Queue):
    def __init__(self, eof_observed: threading.Event) -> None:
        super().__init__(maxsize=64)
        self._eof_observed = eof_observed
        self._shutdown_requested = threading.Event()

    def arm(self) -> None:
        self._shutdown_requested.set()

    def get(self, block=True, timeout=None):
        if self._shutdown_requested.is_set():
            self._eof_observed.wait(2)
        return super().get(block=block, timeout=timeout)


class _ShutdownStdout:
    def __init__(self, process, result_before_eof: bool) -> None:
        self._process = process
        self._result_before_eof = result_before_eof
        self._hello_sent = False
        self._result_sent = False
        self._result: bytes | None = None
        self._request_ready = threading.Event()
        self._closed = threading.Event()
        self.eof_observed = threading.Event()

    def set_result(self, result: bytes) -> None:
        self._result = result
        self._request_ready.set()

    def readline(self, _limit: int = -1) -> bytes:
        if not self._hello_sent:
            self._hello_sent = True
            return encode_message(
                PluginWorkerHello(f"worker-{self._process.pid}", self._process.pid)
            )
        self._request_ready.wait(2)
        if (
            self._result_before_eof
            and not self._result_sent
            and self._result is not None
        ):
            self._result_sent = True
            return self._result
        self._process.returncode = 0 if self._result_sent else 23
        self.eof_observed.set()
        return b""

    def close(self) -> None:
        self._closed.set()
        self._request_ready.set()


class _ShutdownStdin:
    def __init__(self, stdout: _ShutdownStdout, result_success: bool) -> None:
        self._stdout = stdout
        self._result_success = result_success
        self._arm = lambda: None
        self.closed = False

    def write(self, line: bytes) -> int:
        message = decode_message(line)
        if (
            not isinstance(message, PluginLifecycleRequest)
            or message.action is not LifecycleAction.SHUTDOWN
        ):
            raise AssertionError("expected a real shutdown lifecycle request")
        self._arm()
        self._stdout.set_result(
            encode_message(
                PluginLifecycleResult(
                    message.request_id,
                    message.plugin_id,
                    self._result_success,
                    "unloaded" if self._result_success else "error",
                    "" if self._result_success else "shutdown_failed",
                    (),
                )
            )
        )
        return len(line)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _ShutdownSequenceProcess:
    def __init__(
        self, *, result_before_eof: bool, result_success: bool = True
    ) -> None:
        self.pid = 43214
        self.returncode = None
        self.actions: list[str] = []
        self.stdout = _ShutdownStdout(self, result_before_eof)
        self.stdin = _ShutdownStdin(self.stdout, result_success)
        self.stderr = io.BytesIO()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.actions.append("wait")
        if self.returncode is None:
            raise subprocess.TimeoutExpired("worker", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.actions.append("terminate")
        self.returncode = 15

    def kill(self) -> None:
        self.actions.append("kill")
        self.returncode = 9


class _ExitedProcess:
    def __init__(self) -> None:
        self.pid = 43213
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class _PausedEntryLock:
    def __init__(self) -> None:
        self.entering = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __enter__(self):
        self.entering.set()
        self.release.wait(1)
        self._lock.acquire()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self._lock.release()


class _ControlledCommitEventBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.fail_commits = False
        self.commit_attempts = 0

    def record_many(self, events, *, deadline=None) -> bool:
        self.commit_attempts += 1
        if self.fail_commits:
            return False
        return super().record_many(events, deadline=deadline)


class TestSubprocessPluginRuntime(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix=".test-subprocess-runtime-")
        self.addCleanup(temporary.cleanup)
        self.plugin_root = Path(temporary.name) / "plugins" / PLUGIN_ID
        self.plugin_root.mkdir(parents=True)
        self.bus = EventBus()
        self.broker = PluginBroker(
            self.bus, grants={PLUGIN_ID: {"event.emit"}}
        )
        self.broker.register_event_emit_handler()
        self.spec = PluginLoadSpec("plugin.py", ("event_bus",), "1.0.0", 1)

    def _runtime_for(
        self,
        source: str,
        *,
        broker: PluginBroker | None = None,
        generation: int = 1,
        **timeout_overrides: float,
    ) -> SubprocessPluginRuntime:
        (self.plugin_root / "plugin.py").write_text(source, encoding="utf-8")
        spec = PluginLoadSpec("plugin.py", ("event_bus",), "1.0.0", generation)
        timeouts = replace(PluginWorkerTimeouts(), **timeout_overrides)
        runtime = SubprocessPluginRuntime(
            self.plugin_root, spec, broker or self.broker, timeouts=timeouts
        )
        self.addCleanup(runtime.close)
        return runtime

    def _wait_until(self, predicate, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_explicit_os_isolation_false_overrides_container_factory(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        runtime._container_factory = lambda: object()
        runtime._os_isolation = False
        self.assertFalse(runtime._should_use_os_isolation())

    def test_container_factory_enables_isolation_for_non_windows_test_host(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        runtime._container_factory = lambda: object()
        runtime._os_isolation = None
        self.assertTrue(runtime._should_use_os_isolation())

    def test_macos_sandbox_factory_enables_isolation_for_non_macos_test_host(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        runtime._macos_sandbox_factory = lambda: _TrackingMacOSSandbox()
        runtime._os_isolation = None
        self.assertTrue(runtime._should_use_os_isolation())

    def test_macos_staging_failure_is_fail_closed_without_direct_spawn(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        sandbox = _FailingMacOSSandbox()
        runtime._macos_sandbox_factory = lambda: sandbox
        runtime._os_isolation = True
        with patch(
            "adapters.subprocess_plugin_runtime.subprocess.Popen",
            side_effect=AssertionError("direct spawn must not be used"),
        ):
            with self.assertRaises(PluginRuntimeError) as raised:
                runtime.start()

        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_START_FAILED")
        self.assertEqual(sandbox.close_calls, 1)
        self.assertIsNone(runtime._macos_sandbox)

    def test_staged_worker_validation_failure_closes_container(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        container = _TrackingContainer()
        runtime._container_factory = lambda: container
        runtime._os_isolation = True
        valid_worker = Path("staged") / "src" / "runtime" / "plugin_worker.py"
        with patch.object(
            runtime,
            "_validated_worker_path",
            side_effect=[
                valid_worker,
                PluginRuntimeError(
                    "PLUGIN_WORKER_START_FAILED", "staged Worker path drifted"
                ),
            ],
        ):
            with self.assertRaises(PluginRuntimeError) as raised:
                runtime.start()

        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_START_FAILED")
        self.assertEqual(container.close_calls, 1)
        self.assertEqual(container.spawn_calls, 0)
        self.assertIsNone(runtime._container)

    def _assert_early_handshake_fault(self, fault: str, code: str) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        fault_ready = (
            threading.Event() if fault == "eof" else runtime._output_overflow
        )
        output_queue = _FaultBeforeGetQueue(
            fault_ready, maxsize=1 if fault == "queue_full" else 64
        )
        process = _IdleFaultProcess(fault, output_queue.consumer_waiting)
        runtime._output_queue = output_queue

        with patch(
            "adapters.subprocess_plugin_runtime.subprocess.Popen",
            return_value=process,
        ):
            with self.assertRaises(PluginRuntimeError) as raised:
                runtime.start()

        self.assertEqual(raised.exception.code, code)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNotNone(runtime._transport_fault)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        with self.assertRaises(PluginRuntimeError) as later:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(later.exception.code, code)

    def _assert_pre_hello_fault_is_handshake_failure(self, fault: str) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        fault_ready = threading.Event()
        runtime._output_queue = _FaultBeforeGetQueue(fault_ready)
        process = _IdleFaultProcess("eof")
        process.stdout = _PreHelloFaultStdout(fault)

        with patch(
            "adapters.subprocess_plugin_runtime.subprocess.Popen",
            return_value=process,
        ):
            with self.assertRaises(PluginRuntimeError) as raised:
                runtime.start()

        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_HANDSHAKE_FAILED")
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        with self.assertRaises(PluginRuntimeError) as later:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(later.exception.code, "PLUGIN_WORKER_HANDSHAKE_FAILED")

    def test_timeouts_reject_boolean_zero_and_nonfinite_values(self) -> None:
        for invalid in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    PluginWorkerTimeouts(handshake=invalid)

    def test_full_lifecycle_runs_in_one_child_and_reaps_after_shutdown(self) -> None:
        runtime = self._runtime_for(
            "STATE = []\n"
            "def activate(api):\n    STATE.append('active')\n"
            "def deactivate():\n    assert STATE == ['active']\n"
            "def cleanup():\n    STATE.append('clean')\n"
        )

        snapshot = runtime.start()
        results = [
            runtime.invoke(action)
            for action in (
                LifecycleAction.LOAD,
                LifecycleAction.ACTIVATE,
                LifecycleAction.DEACTIVATE,
                LifecycleAction.CLEANUP,
                LifecycleAction.SHUTDOWN,
            )
        ]

        self.assertEqual(snapshot.plugin_id, PLUGIN_ID)
        self.assertGreater(snapshot.pid, 0)
        self.assertEqual(snapshot.generation, 1)
        self.assertEqual(
            [result.status for result in results],
            ["loaded", "enabled", "disabled", "unloaded", "unloaded"],
        )
        self.assertTrue(all(result.success for result in results))
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)

    def test_shutdown_result_queued_before_eof_succeeds_and_reaps_worker(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        process = _ShutdownSequenceProcess(result_before_eof=True)
        output_queue = _ShutdownOrderingQueue(process.stdout.eof_observed)
        process.stdin._arm = output_queue.arm
        runtime._output_queue = output_queue
        with patch(
            "adapters.subprocess_plugin_runtime.subprocess.Popen",
            return_value=process,
        ):
            runtime.start()

        result = runtime.invoke(LifecycleAction.SHUTDOWN)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "unloaded")
        self.assertTrue(process.stdin.closed)
        self.assertIn("wait", process.actions)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._transport_fault)

    def test_shutdown_eof_before_result_remains_a_stable_crash(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        process = _ShutdownSequenceProcess(result_before_eof=False)
        output_queue = _ShutdownOrderingQueue(process.stdout.eof_observed)
        process.stdin._arm = output_queue.arm
        runtime._output_queue = output_queue
        with patch(
            "adapters.subprocess_plugin_runtime.subprocess.Popen",
            return_value=process,
        ):
            runtime.start()

        with self.assertRaises(PluginRuntimeError) as raised:
            runtime.invoke(LifecycleAction.SHUTDOWN)

        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_CRASHED")
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        with self.assertRaises(PluginRuntimeError) as later:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(later.exception.code, "PLUGIN_WORKER_CRASHED")

    def test_shutdown_failure_result_then_eof_is_returned_and_contained(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        process = _ShutdownSequenceProcess(
            result_before_eof=True, result_success=False
        )
        output_queue = _ShutdownOrderingQueue(process.stdout.eof_observed)
        process.stdin._arm = output_queue.arm
        runtime._output_queue = output_queue
        with patch(
            "adapters.subprocess_plugin_runtime.subprocess.Popen",
            return_value=process,
        ):
            runtime.start()

        result = runtime.invoke(LifecycleAction.SHUTDOWN)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error, "shutdown_failed")
        self.assertTrue(
            self._wait_until(lambda: runtime.snapshot.termination_confirmed)
        )
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        with self.assertRaises(PluginRuntimeError) as later:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(later.exception.code, "PLUGIN_WORKER_CRASHED")

    def test_launch_uses_trusted_runtime_cwd_and_explicit_plugin_root(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        real_popen = subprocess.Popen
        captured = {}

        def recording_popen(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return real_popen(args, **kwargs)

        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", recording_popen):
            runtime.start()

        args = captured["args"]
        kwargs = captured["kwargs"]
        self.assertIs(type(args), list)
        self.assertEqual(args[:4], [sys.executable, "-I", "-u", args[3]])
        self.assertTrue(Path(args[3]).is_absolute())
        self.assertEqual(
            args[4:], ["--plugin-root", str(self.plugin_root.resolve())]
        )
        self.assertEqual(Path(kwargs["cwd"]), Path(args[3]).parent)
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["stdin"], subprocess.PIPE)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)
        self.assertNotIn("text", kwargs)

    def test_launch_creates_a_platform_process_group(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        real_popen = subprocess.Popen
        captured = {}

        def recording_popen(args, **kwargs):
            captured["kwargs"] = kwargs
            return real_popen(args, **kwargs)

        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", recording_popen):
            runtime.start()

        kwargs = captured["kwargs"]
        if os.name == "nt":
            self.assertTrue(
                kwargs.get("creationflags", 0) & subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            self.assertIs(kwargs.get("start_new_session"), True)

    def test_real_worker_attaches_process_tree_before_handshake(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")

        runtime.start()

        containment = getattr(runtime, "_process_containment", None)
        self.assertIsNotNone(containment)
        self.assertTrue(containment.is_attached)

        runtime.close()

        self.assertIsNone(runtime._process_containment)

    def test_containment_attachment_failure_reaps_direct_process(self) -> None:
        process = _HandshakeTimeoutProcess()
        runtime = self._runtime_for("def activate(api):\n    pass\n")

        with (
            patch(
                "adapters.subprocess_plugin_runtime.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "adapters.subprocess_plugin_runtime.ProcessTreeContainment.attach",
                side_effect=ProcessContainmentError("controlled attach failure"),
            ),
        ):
            with self.assertRaises(PluginRuntimeError) as raised:
                runtime.start()

        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_START_FAILED")
        self.assertTrue(process.terminated)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._process_containment)
        self.assertIsNone(runtime._worker_temp)

    def test_unconfirmed_tree_cleanup_retains_boundary_for_close_retry(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        process = _ExitedProcess()
        containment = _ControlledContainment()
        worker_temp = _SuccessfulWorkerTemp()
        runtime._process = process
        runtime._process_containment = containment
        runtime._worker_temp = worker_temp

        runtime.close()

        self.assertIs(runtime._process, process)
        self.assertIs(runtime._process_containment, containment)
        self.assertIs(runtime._worker_temp, worker_temp)
        self.assertFalse(runtime.snapshot.termination_confirmed)
        self.assertEqual(containment.close_calls, 0)

        containment.empty = True
        runtime.close()

        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._process_containment)
        self.assertIsNone(runtime._worker_temp)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertEqual(containment.close_calls, 1)

    def test_import_and_activation_exceptions_are_bounded_lifecycle_results(self) -> None:
        import_runtime = self._runtime_for("raise RuntimeError('token=secret-value')\n")
        import_runtime.start()
        imported = import_runtime.invoke(LifecycleAction.LOAD)
        self.assertFalse(imported.success)
        self.assertEqual(imported.status, "error")
        self.assertNotIn("secret-value", imported.error)

        second_root = self.plugin_root.parent / "second-plugin"
        second_root.mkdir()
        (second_root / "plugin.py").write_text(
            "def activate(api):\n    raise RuntimeError('activation failed')\n",
            encoding="utf-8",
        )
        second_spec = PluginLoadSpec("plugin.py", (), "1.0.0", 1)
        second = SubprocessPluginRuntime(
            second_root, second_spec, PluginBroker(self.bus)
        )
        self.addCleanup(second.close)
        second.start()
        self.assertTrue(second.invoke(LifecycleAction.LOAD).success)
        activated = second.invoke(LifecycleAction.ACTIVATE)
        self.assertFalse(activated.success)
        self.assertEqual(activated.error, "plugin_lifecycle_failed: RuntimeError")
        self.assertTrue(second.is_usable)

    def test_successful_lifecycle_records_event_without_calling_subscribers(self) -> None:
        subscriber_called = threading.Event()

        def blocking_subscriber(_event):
            subscriber_called.set()
            time.sleep(0.5)

        self.bus.subscribe("plugin.runtime.activated", blocking_subscriber)
        runtime = self._runtime_for(
            "def activate(api):\n"
            "    result = api.emit_event('plugin.runtime.activated', {'ok': True})\n"
            "    assert result == {'published': True}\n",
            activate=0.2,
            terminate=0.1,
            kill=0.1,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        started = time.monotonic()
        result = runtime.invoke(LifecycleAction.ACTIVATE)
        elapsed = time.monotonic() - started

        self.assertTrue(result.success)
        self.assertLess(elapsed, 0.5)
        self.assertFalse(subscriber_called.is_set())
        self.assertEqual(len(self.bus.get_history()), 1)
        event = self.bus.get_history()[0]
        self.assertEqual(event.event_type, "plugin.runtime.activated")
        self.assertEqual(event.source, f"plugin:{PLUGIN_ID}")

    def test_broker_cumulative_call_cap_denies_without_extra_handler_call(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n"
            f"    for index in range({MAX_BROKER_CALLS + 1}):\n"
            "        api.emit_event('plugin.runtime.call', {'index': index})\n"
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        result = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(result.success)
        self.assertEqual(result.error, "PLUGIN_BROKER_DENIED")
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(runtime.is_usable)

    def test_file_read_broker_serves_files_inside_the_plugin_root(self) -> None:
        (self.plugin_root / "data.txt").write_text(
            "broker-visible", encoding="utf-8"
        )
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    result = api.read_file('data.txt')\n"
            "    assert result == 'broker-visible', result\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus, grants={PLUGIN_ID: {"file.read"}})
        broker.register_event_emit_handler()
        broker.register_file_read_handler()
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "file_read"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(activated.success)
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(runtime.is_usable)

    def test_file_read_without_grant_is_a_stable_worker_denial(self) -> None:
        (self.plugin_root / "data.txt").write_text(
            "secret", encoding="utf-8"
        )
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    api.read_file('data.txt')\n",
            encoding="utf-8",
        )
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "file_read"), "1.0.0", 1),
            self.broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(activated.success)
        self.assertEqual(activated.error, "PLUGIN_BROKER_DENIED")
        self.assertTrue(runtime.is_usable)

    def test_file_list_broker_serves_plugin_root_snapshot(self) -> None:
        (self.plugin_root / "data.txt").write_text("visible", encoding="utf-8")
        (self.plugin_root / "nested").mkdir()
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    result = api.list_dir('.')\n"
            "    names = {item['name']: item['type'] for item in result}\n"
            "    assert names['data.txt'] == 'file', names\n"
            "    assert names['nested'] == 'directory', names\n"
            "    assert names['plugin.py'] == 'file', names\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus, grants={PLUGIN_ID: {"file.list"}})
        broker.register_event_emit_handler()
        broker.register_file_list_handler()
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "file_read"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(activated.success)
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(runtime.is_usable)

    def test_file_list_without_grant_is_a_stable_worker_denial(self) -> None:
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    api.list_dir('.')\n",
            encoding="utf-8",
        )
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "file_read"), "1.0.0", 1),
            self.broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(activated.success)
        self.assertEqual(activated.error, "PLUGIN_BROKER_DENIED")
        self.assertTrue(runtime.is_usable)

    def test_config_get_broker_serves_plugin_bound_config_json(self) -> None:
        (self.plugin_root / "config.json").write_text(
            '{"theme": "dark", "limits": {"retries": 3}}', encoding="utf-8"
        )
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    theme = api.get_config('theme')\n"
            "    limits = api.get_config('limits')\n"
            "    missing = api.get_config('absent', default='fallback')\n"
            "    assert theme == 'dark', theme\n"
            "    assert limits == {'retries': 3}, limits\n"
            "    assert missing == 'fallback', missing\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus, grants={PLUGIN_ID: {"config.get"}})
        broker.register_event_emit_handler()
        broker.register_config_get_handler()
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "system_config"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(activated.success)
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(runtime.is_usable)

    def test_config_get_without_grant_is_a_stable_worker_denial(self) -> None:
        (self.plugin_root / "config.json").write_text(
            '{"theme": "dark"}', encoding="utf-8"
        )
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    api.get_config('theme')\n",
            encoding="utf-8",
        )
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "system_config"), "1.0.0", 1),
            self.broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(activated.success)
        self.assertEqual(activated.error, "PLUGIN_BROKER_DENIED")
        self.assertTrue(runtime.is_usable)

    def test_llm_call_broker_serves_parent_provider(self) -> None:
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    reply = api.call_llm('what color is the sky', model='llama3')\n"
            "    assert reply['text'] == 'blue', reply\n"
            "    assert tuple(reply['tokens']) == (1, 2), reply\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus, grants={PLUGIN_ID: {"llm.call"}})
        broker.register_event_emit_handler()
        broker.register_llm_call_handler(
            lambda prompt, model: {"text": "blue", "tokens": [1, 2]}
        )
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "llm_access"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(activated.success)
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(runtime.is_usable)

    def test_llm_call_without_provider_is_a_stable_worker_denial(self) -> None:
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    api.call_llm('hello')\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus, grants={PLUGIN_ID: {"llm.call"}})
        broker.register_event_emit_handler()
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "llm_access"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(activated.success)
        self.assertEqual(activated.error, "PLUGIN_BROKER_DENIED")
        self.assertTrue(runtime.is_usable)

    def test_network_get_broker_serves_parent_fetch(self) -> None:
        fixture = NetworkFixtureServer()
        self.addCleanup(fixture.close)
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            f"    data = api.get_url('{fixture.base_url}/ok')\n"
            "    assert data['status'] == 200, data\n"
            "    assert data['body'] == '{\"pong\": true}', data\n"
            "    assert 'content-type' in data['headers'], data\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus, grants={PLUGIN_ID: {"network.get"}})
        broker.register_event_emit_handler()
        broker.register_network_get_handler(["127.0.0.1"])
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "network"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(activated.success)
        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(runtime.is_usable)

    def test_network_get_without_allowlist_is_a_stable_worker_denial(self) -> None:
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    api.get_url('http://127.0.0.1:1/probe')\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus, grants={PLUGIN_ID: {"network.get"}})
        broker.register_event_emit_handler()
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "network"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(activated.success)
        self.assertEqual(activated.error, "PLUGIN_BROKER_DENIED")
        self.assertTrue(runtime.is_usable)

    def test_network_get_without_grant_is_a_stable_worker_denial(self) -> None:
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    api.get_url('http://127.0.0.1:1/probe')\n",
            encoding="utf-8",
        )
        broker = PluginBroker(self.bus)
        broker.register_event_emit_handler()
        broker.register_network_get_handler(["127.0.0.1"])
        runtime = SubprocessPluginRuntime(
            self.plugin_root,
            PluginLoadSpec("plugin.py", ("event_bus", "network"), "1.0.0", 1),
            broker,
        )
        self.addCleanup(runtime.close)
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        activated = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(activated.success)
        self.assertEqual(activated.error, "PLUGIN_BROKER_DENIED")
        self.assertTrue(runtime.is_usable)

    def test_event_is_discarded_when_plugin_exceeds_lifecycle_deadline(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n"
            "    api.emit_event('plugin.runtime.before_timeout', {'ok': True})\n"
            "    while True:\n"
            "        pass\n",
            activate=0.2,
            terminate=0.1,
            kill=0.1,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_TIMEOUT"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertEqual(self.bus.get_history(), [])
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())

    def test_failed_event_commit_is_fatal_reaps_worker_and_records_nothing(self) -> None:
        bus = _ControlledCommitEventBus()
        broker = PluginBroker(bus, grants={PLUGIN_ID: {"event.emit"}})
        broker.register_event_emit_handler()
        runtime = self._runtime_for(
            "def activate(api):\n"
            "    api.emit_event('plugin.runtime.commit', {'ok': True})\n",
            broker=broker,
            activate=0.5,
            terminate=0.1,
            kill=0.1,
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)
        bus.fail_commits = True

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_TIMEOUT"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertEqual(bus.commit_attempts, 2)
        self.assertEqual(bus.get_history(), [])
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)

    def test_timeout_terminates_and_reaps_child_without_killing_parent(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    while True:\n        pass\n",
            activate=0.2,
            terminate=0.2,
            kill=0.2,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_TIMEOUT"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)

    def test_child_exit_is_a_crash_and_process_is_reaped(self) -> None:
        runtime = self._runtime_for(
            "import os\n"
            "def activate(api):\n    os._exit(23)\n",
            activate=1,
            terminate=0.2,
            kill=0.2,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_CRASHED"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())

    def test_malformed_stdout_is_protocol_error_and_reaps_child(self) -> None:
        runtime = self._runtime_for(
            "import os\n"
            "def activate(api):\n    os.write(1, b'not-json\\n')\n",
            terminate=0.2,
            kill=0.2,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_PROTOCOL_ERROR"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())

    def test_large_integer_stdout_is_protocol_error_and_reaps_child(self) -> None:
        runtime = self._runtime_for(
            "import os\n"
            "def activate(api):\n"
            "    os.write(1, b'{\"pid\":' + b'9' * 5000 + b'}\\n')\n",
            terminate=0.2,
            kill=0.2,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_PROTOCOL_ERROR"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())

    def test_oversized_stdout_is_output_limit_and_reaps_child(self) -> None:
        runtime = self._runtime_for(
            "import os\n"
            f"def activate(api):\n    os.write(1, b'x' * {MAX_PLUGIN_WORKER_LINE_BYTES} + b'\\n')\n",
            terminate=0.2,
            kill=0.2,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_OUTPUT_LIMIT"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())

    def test_reader_overflow_immediately_marks_runtime_unusable_before_next_write(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n",
            terminate=0.1,
            kill=0.1,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        runtime._output_overflow.set()

        self.assertFalse(runtime.is_usable)
        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_OUTPUT_LIMIT"):
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())

    def test_idle_stdout_eof_automatically_contains_worker_and_latches_crash(self) -> None:
        process = _IdleFaultProcess("eof")
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", return_value=process):
            runtime.start()

        process.stdout.trigger()

        self.assertTrue(
            self._wait_until(lambda: runtime.snapshot.termination_confirmed)
        )
        self.assertIn("terminate", process.actions)
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        with self.assertRaises(PluginRuntimeError) as raised:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_CRASHED")

    def test_idle_stdout_reader_error_automatically_contains_worker_and_latches_crash(self) -> None:
        process = _IdleFaultProcess("reader_error")
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", return_value=process):
            runtime.start()

        process.stdout.trigger()

        self.assertTrue(
            self._wait_until(lambda: runtime.snapshot.termination_confirmed)
        )
        self.assertIn("terminate", process.actions)
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        with self.assertRaises(PluginRuntimeError) as raised:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_CRASHED")

    def test_eof_after_hello_before_ready_fails_start_and_contains_worker(self) -> None:
        self._assert_early_handshake_fault("eof", "PLUGIN_WORKER_CRASHED")

    def test_eof_before_hello_is_a_stable_handshake_failure(self) -> None:
        self._assert_pre_hello_fault_is_handshake_failure("eof")

    def test_reader_error_before_hello_is_a_stable_handshake_failure(self) -> None:
        self._assert_pre_hello_fault_is_handshake_failure("reader_error")

    def test_oversized_stdout_after_hello_before_ready_fails_start(self) -> None:
        self._assert_early_handshake_fault(
            "oversized", "PLUGIN_WORKER_OUTPUT_LIMIT"
        )

    def test_full_output_queue_after_hello_before_ready_fails_start(self) -> None:
        self._assert_early_handshake_fault(
            "queue_full", "PLUGIN_WORKER_OUTPUT_LIMIT"
        )

    def test_idle_oversized_stdout_automatically_contains_worker_and_latches_limit(self) -> None:
        process = _IdleFaultProcess("oversized")
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", return_value=process):
            runtime.start()

        process.stdout.trigger()

        self.assertTrue(
            self._wait_until(lambda: runtime.snapshot.termination_confirmed)
        )
        self.assertIn("terminate", process.actions)
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        with self.assertRaises(PluginRuntimeError) as raised:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_OUTPUT_LIMIT")

    def test_idle_full_output_queue_automatically_contains_worker_and_latches_limit(self) -> None:
        process = _IdleFaultProcess("queue_full")
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n", terminate=0.05, kill=0.05
        )
        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", return_value=process):
            runtime.start()

        process.stdout.trigger()

        self.assertTrue(
            self._wait_until(lambda: runtime.snapshot.termination_confirmed)
        )
        self.assertIn("terminate", process.actions)
        self.assertIn("wait", process.actions)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        with self.assertRaises(PluginRuntimeError) as raised:
            runtime.invoke(LifecycleAction.ACTIVATE)
        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_OUTPUT_LIMIT")

    def test_normal_termination_started_before_fault_latch_keeps_eof_expected(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        paused_lock = _PausedEntryLock()
        runtime._transport_ready.set()
        runtime._transport_fault_lock = paused_lock
        observer = threading.Thread(
            target=runtime._observe_transport_fault,
            args=("PLUGIN_WORKER_CRASHED", "Worker process ended before a result"),
        )
        observer.start()
        self.assertTrue(paused_lock.entering.wait(1))

        runtime._termination_started.set()
        paused_lock.release.set()
        observer.join(timeout=1)

        self.assertFalse(observer.is_alive())
        self.assertIsNone(runtime._transport_fault)

    def test_pending_containment_cleanup_thread_is_not_replaced(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        pending = threading.Thread()
        runtime._containment_thread = pending

        runtime._schedule_transport_containment()

        self.assertIs(runtime._containment_thread, pending)

    def test_stale_result_cannot_replace_the_active_request_result(self) -> None:
        stale = encode_message(
            PluginLifecycleResult(
                "request-1-1", PLUGIN_ID, True, "enabled", "", ()
            )
        )
        runtime = self._runtime_for(
            "import os\n"
            f"STALE = {stale!r}\n"
            "def activate(api):\n    os.write(1, STALE)\n",
            terminate=0.2,
            kill=0.2,
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_PROTOCOL_ERROR"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(runtime.is_usable)
        self.assertTrue(runtime.snapshot.termination_confirmed)

    def test_older_generation_cannot_open_a_broker_session_or_mutate_events(self) -> None:
        newer = self._runtime_for("def activate(api):\n    pass\n", generation=2)
        newer.start()
        self.assertTrue(newer.invoke(LifecycleAction.LOAD).success)

        old_root = self.plugin_root.parent / "old-generation-plugin"
        old_root.mkdir()
        (old_root / "plugin.py").write_text("def activate(api):\n    pass\n", encoding="utf-8")
        old_spec = PluginLoadSpec("plugin.py", ("event_bus",), "1.0.0", 1)
        old_broker = PluginBroker(
            self.bus, grants={"old-generation-plugin": {"event.emit"}}
        )
        old = SubprocessPluginRuntime(old_root, old_spec, old_broker)
        self.addCleanup(old.close)
        old.start()
        self.assertTrue(old.invoke(LifecycleAction.LOAD).success)

        newer_session = old_broker.begin_lifecycle(
            "old-generation-plugin", "request-newer", ("event_bus",), 2
        )
        self.assertIsNotNone(newer_session)
        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_PROTOCOL_ERROR"):
            old.invoke(LifecycleAction.ACTIVATE)

        self.assertEqual(self.bus.get_history(), [])
        self.assertFalse(old.is_usable)

    def test_child_receives_only_allowlisted_environment_and_fresh_temp_dir(self) -> None:
        runtime = self._runtime_for(
            "import json, os\n"
            "def activate(api):\n"
            "    with open(os.path.join(os.environ['TMPDIR'], 'environment.json'), 'w', encoding='utf-8') as stream:\n"
            "        json.dump(dict(os.environ), stream, sort_keys=True)\n"
        )
        sentinel = {
            "JARVIS_SERVICE_SECRET": "must-not-cross",
            "OLLAMA_HOST": "must-not-cross",
            "HTTPS_PROXY": "must-not-cross",
            "AWS_SECRET_ACCESS_KEY": "must-not-cross",
            "PYTHONPATH": "must-not-cross",
            "ARBITRARY_PARENT_VALUE": "must-not-cross",
        }
        with patch.dict(os.environ, sentinel, clear=False):
            runtime.start()
        runtime.invoke(LifecycleAction.LOAD)
        runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertIsNotNone(runtime._worker_temp)
        child_env = json.loads(
            (Path(runtime._worker_temp.name) / "environment.json").read_text(
                encoding="utf-8"
            )
        )
        allowed = {
            "PATH", "PATHEXT", "SystemRoot", "WINDIR", "ComSpec",
            "LOCALAPPDATA",
            "PYTHONIOENCODING", "PYTHONUNBUFFERED", "PYTHONNOUSERSITE",
            "TMP", "TEMP", "TMPDIR",
        }
        child_keys = {key.casefold() for key in child_env}
        self.assertLessEqual(child_keys, {key.casefold() for key in allowed})
        self.assertTrue({key.casefold() for key in sentinel}.isdisjoint(child_keys))
        self.assertEqual(child_env["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(child_env["PYTHONUNBUFFERED"], "1")
        self.assertEqual(child_env["PYTHONNOUSERSITE"], "1")
        if runtime._container is None:
            self.assertEqual(
                len({child_env[name] for name in ("TMP", "TEMP", "TMPDIR")}), 1
            )
        else:
            self.assertEqual(
                child_env["TMPDIR"],
                runtime._container.writable_root.as_posix().replace("/", "\\"),
            )
        self.assertNotEqual(Path(child_env["TMP"]).resolve(), self.plugin_root)

    def test_plugin_import_does_not_change_parent_modules_or_path(self) -> None:
        module_name = "plugin_dependency_probe_iteration_141"
        (self.plugin_root / f"{module_name}.py").write_text("VALUE = 41\n", encoding="utf-8")
        runtime = self._runtime_for(
            f"import {module_name}\n"
            "def activate(api):\n"
            f"    assert {module_name}.VALUE == 41\n"
        )
        before_path = list(sys.path)
        before_modules = set(sys.modules)

        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)
        runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertEqual(sys.path, before_path)
        self.assertEqual(set(sys.modules), before_modules)
        self.assertNotIn(module_name, sys.modules)
        self.assertFalse(any(name.startswith("jarvis_plugin_id_") for name in set(sys.modules) - before_modules))

    def test_stderr_is_retained_as_a_private_eight_kib_tail_only(self) -> None:
        runtime = self._runtime_for(
            "import sys\n"
            "def activate(api):\n"
            "    sys.stderr.write('x' * 9000 + 'PRIVATE-SENTINEL')\n"
            "    sys.stderr.flush()\n"
            "    raise RuntimeError('public failure')\n"
        )
        runtime.start()
        runtime.invoke(LifecycleAction.LOAD)

        result = runtime.invoke(LifecycleAction.ACTIVATE)
        runtime.close()

        self.assertFalse(result.success)
        self.assertNotIn("PRIVATE-SENTINEL", result.error)
        self.assertLessEqual(len(runtime._stderr_buffer), 8 * 1024)
        self.assertTrue(bytes(runtime._stderr_buffer).endswith(b"PRIVATE-SENTINEL"))

    def test_handshake_timeout_terminates_and_reaps_controlled_child(self) -> None:
        process = _HandshakeTimeoutProcess()
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n",
            handshake=0.05,
            terminate=0.05,
            kill=0.05,
        )

        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_TIMEOUT"):
                runtime.start()

        self.assertTrue(process.terminated)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.is_usable)

    def test_reader_thread_start_failure_terminates_and_reaps_worker(self) -> None:
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n",
            terminate=0.1,
            kill=0.1,
        )

        with patch.object(threading.Thread, "start", side_effect=RuntimeError("no thread")):
            with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_START_FAILED"):
                runtime.start()

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)
        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._stderr_thread)
        self.assertIsNone(runtime._worker_temp)
        renamed_root = self.plugin_root.with_name("reader-start-released")
        self.plugin_root.rename(renamed_root)
        renamed_root.rename(self.plugin_root)

    def test_oversized_outbound_request_fails_stably_and_reaps_worker(self) -> None:
        oversized_spec = PluginLoadSpec(
            "x" * MAX_PLUGIN_WORKER_LINE_BYTES, (), "1.0.0", 1
        )
        runtime = SubprocessPluginRuntime(
            self.plugin_root, oversized_spec, self.broker,
            timeouts=replace(PluginWorkerTimeouts(), terminate=0.1, kill=0.1),
        )
        self.addCleanup(runtime.close)
        runtime.start()

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_PROTOCOL_ERROR"):
            runtime.invoke(LifecycleAction.LOAD)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertFalse(runtime.is_usable)

    def test_failed_worker_temp_cleanup_retains_handle_for_close_retry(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        worker_temp = _FlakyWorkerTemp()
        runtime._worker_temp = worker_temp

        runtime.close()

        self.assertIs(runtime._worker_temp, worker_temp)
        runtime.close()
        self.assertEqual(worker_temp.calls, 2)
        self.assertIsNone(runtime._worker_temp)

    def test_close_retains_all_ownership_until_confirmed_reader_exit(self) -> None:
        runtime = self._runtime_for("def activate(api):\n    pass\n")
        process = _ExitedProcess()
        release_reader = threading.Event()
        reader = threading.Thread(target=release_reader.wait)
        reader.start()
        self.addCleanup(release_reader.set)
        worker_temp = tempfile.TemporaryDirectory(prefix=".test-worker-ownership-")
        self.addCleanup(worker_temp.cleanup)
        worker_temp_path = Path(worker_temp.name)
        runtime._process = process
        runtime._stdout_thread = reader
        runtime._worker_temp = worker_temp

        runtime.close()

        self.assertIs(runtime._process, process)
        self.assertIs(runtime._stdout_thread, reader)
        self.assertIs(runtime._worker_temp, worker_temp)
        self.assertTrue(worker_temp_path.exists())

        release_reader.set()
        reader.join(timeout=1)
        runtime.close()

        self.assertIsNone(runtime._process)
        self.assertIsNone(runtime._stdout_thread)
        self.assertIsNone(runtime._worker_temp)
        self.assertFalse(worker_temp_path.exists())

    def test_trusted_worker_validator_accepts_regular_worker(self) -> None:
        source_root = Path(tempfile.mkdtemp(prefix=".test-trusted-worker-"))
        self.addCleanup(shutil.rmtree, source_root, ignore_errors=True)
        worker = source_root / "runtime" / "plugin_worker.py"
        worker.parent.mkdir()
        worker.write_text("# trusted worker\n", encoding="utf-8")
        runtime = self._runtime_for("def activate(api):\n    pass\n")

        self.assertEqual(runtime._validated_worker_path(source_root), worker.resolve())

    def test_trusted_worker_validator_rejects_raw_worker_link_before_resolve(self) -> None:
        source_root = Path(tempfile.mkdtemp(prefix=".test-trusted-worker-link-"))
        self.addCleanup(shutil.rmtree, source_root, ignore_errors=True)
        runtime_dir = source_root / "runtime"
        runtime_dir.mkdir()
        target = source_root / "worker-target.py"
        target.write_text("# target\n", encoding="utf-8")
        worker = runtime_dir / "plugin_worker.py"
        worker.symlink_to(target)
        runtime = self._runtime_for("def activate(api):\n    pass\n")

        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen") as popen:
            with patch.object(Path, "resolve", side_effect=AssertionError("resolved link")):
                with self.assertRaises(PluginRuntimeError) as raised:
                    runtime._validated_worker_path(source_root)

        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_START_FAILED")
        popen.assert_not_called()

    def test_trusted_worker_validator_rejects_raw_runtime_link_before_resolve(self) -> None:
        source_root = Path(tempfile.mkdtemp(prefix=".test-trusted-runtime-link-"))
        self.addCleanup(shutil.rmtree, source_root, ignore_errors=True)
        target_runtime = source_root / "runtime-target"
        target_runtime.mkdir()
        (target_runtime / "plugin_worker.py").write_text(
            "# target\n", encoding="utf-8"
        )
        runtime_link = source_root / "runtime"
        runtime_link.symlink_to(target_runtime, target_is_directory=True)
        runtime = self._runtime_for("def activate(api):\n    pass\n")

        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen") as popen:
            with patch.object(Path, "resolve", side_effect=AssertionError("resolved link")):
                with self.assertRaises(PluginRuntimeError) as raised:
                    runtime._validated_worker_path(source_root)

        self.assertEqual(raised.exception.code, "PLUGIN_WORKER_START_FAILED")
        popen.assert_not_called()

    def test_unconfirmed_termination_is_not_reusable_or_silently_replaced(self) -> None:
        process = _UnreapableProcess()
        runtime = self._runtime_for(
            "def activate(api):\n    pass\n",
            terminate=0.01,
            kill=0.01,
        )
        with patch("adapters.subprocess_plugin_runtime.subprocess.Popen", return_value=process):
            runtime.start()

        runtime.close()

        self.assertFalse(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.is_usable)
        self.assertTrue(runtime.process_is_alive())
        self.assertIn("terminate", process.actions)
        self.assertIn("kill", process.actions)
        with self.assertRaises(PluginRuntimeError):
            runtime.start()
        process.released = True
        runtime.close()
        self.assertIsNone(runtime._process)


if __name__ == "__main__":
    unittest.main()
