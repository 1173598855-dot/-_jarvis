"""Integration tests for the parent-owned Plugin Worker Popen runtime."""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adapters.subprocess_plugin_runtime import (
    PluginRuntimeError,
    PluginWorkerTimeouts,
    SubprocessPluginRuntime,
)
from core.contracts.plugin_worker_protocol import LifecycleAction, PluginLoadSpec
from core.kernel.event_bus import EventBus
from core.kernel.plugin_broker import PluginBroker


class TestSubprocessPluginRuntime(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.plugins_root = Path(self.directory.name) / "plugins"
        self.plugins_root.mkdir()
        self.bus = EventBus()
        self.broker = PluginBroker(
            self.bus,
            grants={"example-plugin": {"event.emit"}},
        )
        self.broker.register_event_emit_handler()

    def _runtime_for(self, source, **timeout_overrides):
        root = self.plugins_root / "example-plugin"
        root.mkdir()
        (root / "plugin.py").write_text(source, encoding="utf-8")
        defaults = {
            "handshake_seconds": 2,
            "load_seconds": 2,
            "activate_seconds": 2,
            "deactivate_seconds": 2,
            "cleanup_seconds": 2,
            "shutdown_seconds": 2,
            "terminate_seconds": 0.2,
            "kill_seconds": 0.2,
        }
        defaults.update(timeout_overrides)
        runtime = SubprocessPluginRuntime(
            root,
            PluginLoadSpec(
                entry_point="plugin.py",
                permissions=("event_bus",),
                api_version="1.0.0",
                generation=1,
            ),
            self.broker,
            timeouts=PluginWorkerTimeouts(**defaults),
        )
        self.addCleanup(runtime.close)
        return runtime

    def test_successful_lifecycle_uses_one_owned_child(self):
        runtime = self._runtime_for(
            "COUNTER = 0\n"
            "def activate(api):\n"
            "    global COUNTER\n"
            "    COUNTER += 1\n"
            "def deactivate():\n"
            "    pass\n"
            "def cleanup():\n"
            "    pass\n"
        )

        snapshot = runtime.start()
        self.assertNotEqual(snapshot.pid, os.getpid())
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)
        self.assertTrue(runtime.invoke(LifecycleAction.ACTIVATE).success)
        self.assertTrue(runtime.invoke(LifecycleAction.DEACTIVATE).success)
        self.assertTrue(runtime.invoke(LifecycleAction.CLEANUP).success)

        runtime.close()

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertTrue(runtime._process.stdout.closed)
        self.assertTrue(runtime._process.stderr.closed)

    def test_timeout_terminates_and_reaps_child_without_killing_parent(self):
        runtime = self._runtime_for(
            "def activate(api):\n"
            "    while True:\n"
            "        pass\n",
            activate_seconds=0.2,
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_TIMEOUT"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())
        self.assertTrue(os.getpid() > 0)

    def test_broker_call_is_routed_to_parent_owned_event_bus(self):
        runtime = self._runtime_for(
            "def activate(api):\n"
            "    result = api.emit_event('plugin.activated', {'plugin_id': api.plugin_id})\n"
            "    assert result.allowed\n"
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)

        result = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(result.success)
        event = self.bus.get_history()[-1]
        self.assertEqual(event.source, "plugin:example-plugin")
        self.assertEqual(event.event_type, "plugin.activated")

    def test_protocol_corruption_marks_runtime_unusable_and_reaps_child(self):
        runtime = self._runtime_for(
            "import sys\n"
            "def activate(api):\n"
            "    sys.stdout.buffer.write(b'not-json\\n')\n"
            "    sys.stdout.buffer.flush()\n"
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_PROTOCOL_ERROR"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(runtime.is_usable)
        self.assertTrue(runtime.snapshot.termination_confirmed)

    def test_oversized_stdout_marks_runtime_unusable_and_reaps_child(self):
        runtime = self._runtime_for(
            "import sys\n"
            "def activate(api):\n"
            "    sys.stdout.buffer.write(b'x' * 65537)\n"
            "    sys.stdout.buffer.flush()\n"
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_OUTPUT_LIMIT"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertFalse(runtime.is_usable)
        self.assertTrue(runtime.snapshot.termination_confirmed)

    def test_child_exit_is_contained_and_reaped(self):
        runtime = self._runtime_for(
            "import os\n"
            "def activate(api):\n"
            "    os._exit(7)\n"
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_WORKER_CRASHED"):
            runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertFalse(runtime.process_is_alive())

    def test_parent_module_and_path_state_are_unchanged(self):
        modules_before = set(sys.modules)
        path_before = list(sys.path)
        runtime = self._runtime_for("def activate(api):\n    pass\n")

        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)
        runtime.close()

        self.assertEqual(sys.path, path_before)
        self.assertEqual(set(sys.modules), modules_before)

    def test_sanitized_environment_omits_service_secret(self):
        runtime = self._runtime_for(
            "import os\n"
            "def activate(api):\n"
            "    result = api.emit_event('plugin.environment', {'value': os.environ.get('JARVIS_SECRET')})\n"
            "    assert result.allowed\n"
        )
        with patch.dict(os.environ, {"JARVIS_SECRET": "secret-value"}, clear=False):
            runtime.start()
            self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)
            self.assertTrue(runtime.invoke(LifecycleAction.ACTIVATE).success)

        self.assertIsNone(self.bus.get_history()[-1].data["value"])

    def test_stderr_capture_is_bounded_without_public_error_leakage(self):
        runtime = self._runtime_for(
            "import sys\n"
            "def activate(api):\n"
            "    sys.stderr.write('x' * 9000)\n"
            "    sys.stderr.flush()\n"
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)
        self.assertTrue(runtime.invoke(LifecycleAction.ACTIVATE).success)

        runtime.close()

        self.assertEqual(len(runtime.stderr_text.encode("utf-8")), 8192)

    def test_broker_call_limit_stops_parent_side_effects(self):
        runtime = self._runtime_for(
            "def activate(api):\n"
            "    for index in range(33):\n"
            "        api.emit_event('plugin.activated', {'index': index})\n"
        )
        runtime.start()
        self.assertTrue(runtime.invoke(LifecycleAction.LOAD).success)

        result = runtime.invoke(LifecycleAction.ACTIVATE)

        self.assertTrue(result.success)
        self.assertEqual(len(self.bus.get_history()), 32)

    def test_import_failure_is_returned_without_crashing_parent(self):
        runtime = self._runtime_for("raise RuntimeError('secret-value')\n")
        runtime.start()

        result = runtime.invoke(LifecycleAction.LOAD)

        self.assertFalse(result.success)
        self.assertEqual(result.error, "PLUGIN_LIFECYCLE_FAILED")
        self.assertTrue(runtime.is_usable)

    def test_symlinked_entrypoint_is_rejected_before_worker_start(self):
        root = self.plugins_root / "example-plugin"
        root.mkdir()
        target = root / "alternate.py"
        target.write_text("def activate(api):\n    pass\n", encoding="utf-8")
        try:
            (root / "plugin.py").symlink_to(target)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

        with self.assertRaisesRegex(PluginRuntimeError, "PLUGIN_ENTRYPOINT_INVALID"):
            SubprocessPluginRuntime(
                root,
                PluginLoadSpec(
                    entry_point="plugin.py",
                    permissions=("event_bus",),
                    api_version="1.0.0",
                    generation=1,
                ),
                self.broker,
            )

    def test_unconfirmed_termination_remains_visible_on_snapshot(self):
        class StubbornProcess:
            pid = 123
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()

            def __init__(self):
                self.terminate_calls = 0
                self.kill_calls = 0

            def poll(self):
                return None

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("worker", timeout)

            def terminate(self):
                self.terminate_calls += 1

            def kill(self):
                self.kill_calls += 1

        runtime = self._runtime_for("def activate(api):\n    pass\n")
        process = StubbornProcess()
        runtime._process = process

        runtime.close()

        self.assertFalse(runtime.snapshot.termination_confirmed)
        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)


if __name__ == "__main__":
    unittest.main()
