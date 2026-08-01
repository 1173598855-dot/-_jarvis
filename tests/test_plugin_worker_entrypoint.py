"""Tests for the child-only Plugin Worker entrypoint."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts.plugin_worker_protocol import (
    LifecycleAction,
    PluginBrokerResult,
    PluginLifecycleRequest,
    PluginLoadSpec,
    decode_message,
    encode_message,
)
from runtime.plugin_worker import PluginWorkerServer


ROOT = Path(__file__).parent.parent


def load_request(plugin_id="example-plugin", generation=1, entry_point="plugin.py"):
    return PluginLifecycleRequest(
        request_id="load-1",
        plugin_id=plugin_id,
        action=LifecycleAction.LOAD,
        payload=PluginLoadSpec(
            entry_point=entry_point,
            permissions=("event_bus",),
            api_version="1.0.0",
            generation=generation,
        ).to_dict(),
    )


def lifecycle_request(action, request_id):
    return PluginLifecycleRequest(
        request_id=request_id,
        plugin_id="example-plugin",
        action=action,
        payload={},
    )


class TestPluginWorkerEntrypoint(unittest.TestCase):
    def _worker_for(self, source, *, stdin=None, stdout=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "plugin.py").write_text(source, encoding="utf-8")
        return PluginWorkerServer(
            stdin or io.BytesIO(),
            stdout or io.BytesIO(),
            io.BytesIO(),
            root,
        )

    def test_worker_imports_only_after_valid_load_and_keeps_module_state(self):
        worker = self._worker_for(
            "COUNTER = 0\n"
            "def activate(api):\n"
            "    global COUNTER\n"
            "    COUNTER += 1\n"
        )

        self.assertEqual(worker.hello().to_dict()["kind"], "hello")
        self.assertTrue(worker.request(load_request()).success)
        self.assertTrue(
            worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "activate-1")).success
        )
        self.assertTrue(
            worker.request(lifecycle_request(LifecycleAction.DEACTIVATE, "deactivate-1")).success
        )
        self.assertEqual(worker.module.COUNTER, 1)

    def test_load_rejects_entrypoint_outside_plugin_root(self):
        worker = self._worker_for("def activate(api):\n    pass\n")

        result = worker.request(load_request(entry_point="../outside.py"))

        self.assertFalse(result.success)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error, "PLUGIN_LIFECYCLE_FAILED")
        self.assertIsNone(worker.module)

    def test_shutdown_before_load_is_a_successful_unloaded_transition(self):
        worker = self._worker_for("def activate(api):\n    pass\n")

        result = worker.request(
            lifecycle_request(LifecycleAction.SHUTDOWN, "shutdown-1")
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "unloaded")

    def test_lifecycle_exception_and_system_exit_return_bounded_errors(self):
        for source in (
            "def activate(api):\n    raise RuntimeError('secret-value')\n",
            "def activate(api):\n    raise SystemExit(7)\n",
        ):
            with self.subTest(source=source):
                worker = self._worker_for(source)
                self.assertTrue(worker.request(load_request()).success)

                result = worker.request(
                    lifecycle_request(LifecycleAction.ACTIVATE, "activate-1")
                )

                self.assertFalse(result.success)
                self.assertEqual(result.status, "error")
                self.assertEqual(result.error, "PLUGIN_LIFECYCLE_FAILED")

    def test_worker_uses_one_matching_broker_result_for_api_call(self):
        broker_result = PluginBrokerResult(
            request_id="activate-1",
            call_id="broker-1",
            plugin_id="example-plugin",
            allowed=True,
            result={"emitted": True},
            error="",
        )
        stdout = io.BytesIO()
        worker = self._worker_for(
            "def activate(api):\n"
            "    result = api.emit_event('plugin.activated', {'plugin_id': api.plugin_id})\n"
            "    assert result.allowed\n",
            stdin=io.BytesIO(encode_message(broker_result)),
            stdout=stdout,
        )
        self.assertTrue(worker.request(load_request()).success)

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "activate-1"))

        self.assertTrue(result.success)
        message = decode_message(stdout.getvalue())
        self.assertEqual(message.to_dict()["kind"], "broker_request")
        self.assertEqual(message.request_id, "activate-1")
        self.assertEqual(message.call_id, "broker-1")

    def test_invalid_broker_result_is_contained_by_lifecycle_result(self):
        invalid_result = PluginBrokerResult(
            request_id="wrong-request",
            call_id="broker-1",
            plugin_id="example-plugin",
            allowed=True,
            result={"emitted": True},
            error="",
        )
        worker = self._worker_for(
            "def activate(api):\n"
            "    api.emit_event('plugin.activated', {})\n",
            stdin=io.BytesIO(encode_message(invalid_result)),
        )
        self.assertTrue(worker.request(load_request()).success)

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "activate-1"))

        self.assertFalse(result.success)
        self.assertEqual(result.error, "PLUGIN_LIFECYCLE_FAILED")

    def test_unavailable_child_api_capability_returns_broker_denial(self):
        denied_result = PluginBrokerResult(
            request_id="activate-1",
            call_id="broker-1",
            plugin_id="example-plugin",
            allowed=False,
            result=None,
            error="PLUGIN_BROKER_DENIED",
        )
        worker = self._worker_for(
            "def activate(api):\n"
            "    result = api.get_config('service-token')\n"
            "    assert not result.allowed\n"
            "    assert result.error == 'PLUGIN_BROKER_DENIED'\n",
            stdin=io.BytesIO(encode_message(denied_result)),
        )
        self.assertTrue(worker.request(load_request()).success)

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "activate-1"))

        self.assertTrue(result.success)

    def test_main_does_not_construct_a_core_manager_in_the_plugin_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugin.py").write_text("def activate(api):\n    pass\n", encoding="utf-8")
            payload = b"".join(
                (
                    encode_message(load_request()),
                    encode_message(
                        lifecycle_request(LifecycleAction.SHUTDOWN, "shutdown-1")
                    ),
                )
            )

            completed = subprocess.run(
                [sys.executable, "-I", "-u", str(ROOT / "src" / "runtime" / "plugin_worker.py")],
                cwd=root,
                input=payload,
                capture_output=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
            self.assertFalse((root / "plugins").exists())

    def test_module_names_are_unique_per_generation(self):
        source = "def activate(api):\n    pass\n"
        first = self._worker_for(source)
        second = self._worker_for(source)

        self.assertTrue(first.request(load_request(generation=1)).success)
        self.assertTrue(second.request(load_request(generation=2)).success)

        self.assertNotEqual(first.module.__name__, second.module.__name__)

    def test_serve_writes_hello_and_one_result_per_lifecycle_request(self):
        input_lines = b"".join(
            (
                encode_message(load_request()),
                encode_message(lifecycle_request(LifecycleAction.SHUTDOWN, "shutdown-1")),
            )
        )
        stdout = io.BytesIO()
        worker = self._worker_for(
            "def activate(api):\n    pass\n",
            stdin=io.BytesIO(input_lines),
            stdout=stdout,
        )

        self.assertEqual(worker.serve(), 0)
        messages = [decode_message(line + b"\n") for line in stdout.getvalue().splitlines()]

        self.assertEqual([message.to_dict()["kind"] for message in messages], [
            "hello",
            "lifecycle_result",
            "lifecycle_result",
        ])
        self.assertTrue(messages[1].success)
        self.assertTrue(messages[2].success)


if __name__ == "__main__":
    unittest.main()
