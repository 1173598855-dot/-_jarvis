"""Tests for the child-only plugin worker entrypoint."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts.plugin_worker_protocol import (
    MAX_PLUGIN_WORKER_LINE_BYTES,
    LifecycleAction,
    PluginBrokerResult,
    PluginLifecycleRequest,
    PluginLoadSpec,
    decode_message,
    encode_message,
)
from core.kernel.plugin_sdk import XiaoYiPluginAPI
from core.kernel.worker_filesystem_isolation import WorkerFilesystemIsolationError
from core.kernel.worker_network_isolation import WorkerNetworkIsolationError
from core.kernel.worker_resource_limits import WorkerResourceLimitError
from runtime.plugin_worker import PluginWorkerServer, main

PLUGIN_ID = "fixture-plugin"


def load_request(
    request_id: str = "request-load",
    generation: int = 1,
    plugin_id: str = PLUGIN_ID,
) -> PluginLifecycleRequest:
    return PluginLifecycleRequest(
        request_id=request_id,
        plugin_id=plugin_id,
        action=LifecycleAction.LOAD,
        payload=PluginLoadSpec(
            entry_point="plugin.py",
            permissions=("event_bus",),
            api_version="1.0.0",
            generation=generation,
        ).to_dict(),
    )


def lifecycle_request(action: LifecycleAction, request_id: str) -> PluginLifecycleRequest:
    return PluginLifecycleRequest(
        request_id=request_id,
        plugin_id=PLUGIN_ID,
        action=action,
        payload={},
    )


class TestPluginWorkerEntrypoint(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(prefix=".test-plugin-worker-")
        self.plugin_root = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _worker_for(self, source: str, stdin: io.BytesIO | None = None) -> PluginWorkerServer:
        (self.plugin_root / "plugin.py").write_text(source, encoding="utf-8")
        return PluginWorkerServer(
            stdin=stdin or io.BytesIO(),
            stdout=io.BytesIO(),
            stderr=io.StringIO(),
            plugin_root=self.plugin_root,
        )

    def test_main_uses_only_the_explicit_plugin_root_argument(self) -> None:
        expected_root = self.plugin_root.resolve()
        with patch.object(sys, "argv", ["plugin_worker.py", "--plugin-root", str(expected_root)]):
            with patch.object(sys, "path", list(sys.path)):
                with patch("runtime.plugin_worker.PluginWorkerServer") as server:
                    server.return_value.serve.return_value = 0

                    self.assertEqual(main(), 0)

        self.assertEqual(server.call_args.args[3], expected_root)

    def test_main_fails_closed_when_resource_budgets_cannot_be_enforced(self) -> None:
        expected_root = self.plugin_root.resolve()
        with patch.object(
            sys, "argv", ["plugin_worker.py", "--plugin-root", str(expected_root)]
        ):
            with patch.object(sys, "path", list(sys.path)):
                with patch(
                    "runtime.plugin_worker.apply_worker_resource_limits",
                    side_effect=WorkerResourceLimitError("denied"),
                ):
                    with patch("runtime.plugin_worker.PluginWorkerServer") as server:
                        self.assertEqual(main(), 2)

        server.assert_not_called()

    def test_main_applies_resource_budgets_before_serving(self) -> None:
        expected_root = self.plugin_root.resolve()
        order: list[str] = []
        with patch.object(
            sys, "argv", ["plugin_worker.py", "--plugin-root", str(expected_root)]
        ):
            with patch.object(sys, "path", list(sys.path)):
                with patch(
                    "runtime.plugin_worker.apply_worker_resource_limits",
                    side_effect=lambda: order.append("limits"),
                ):
                    with patch("runtime.plugin_worker.PluginWorkerServer") as server:
                        server.return_value.serve.side_effect = lambda: (
                            order.append("serve"),
                            0,
                        )[1]

                        self.assertEqual(main(), 0)

        self.assertEqual(order, ["limits", "serve"])

    def test_main_fails_closed_when_network_isolation_cannot_be_enforced(self) -> None:
        expected_root = self.plugin_root.resolve()
        with patch.object(
            sys, "argv", ["plugin_worker.py", "--plugin-root", str(expected_root)]
        ):
            with patch.object(sys, "path", list(sys.path)):
                with patch(
                    "runtime.plugin_worker.isolate_worker_network",
                    side_effect=WorkerNetworkIsolationError("denied"),
                ):
                    with patch("runtime.plugin_worker.PluginWorkerServer") as server:
                        self.assertEqual(main(), 2)

        server.assert_not_called()

    def test_main_isolates_network_before_loading_or_serving(self) -> None:
        expected_root = self.plugin_root.resolve()
        order: list[str] = []
        with patch.object(
            sys, "argv", ["plugin_worker.py", "--plugin-root", str(expected_root)]
        ):
            with patch.object(sys, "path", list(sys.path)):
                with patch(
                    "runtime.plugin_worker.apply_worker_resource_limits",
                    side_effect=lambda: order.append("limits"),
                ):
                    with patch(
                        "runtime.plugin_worker.isolate_worker_network",
                        side_effect=lambda: order.append("network"),
                    ):
                        with patch("runtime.plugin_worker.PluginWorkerServer") as server:
                            server.return_value.serve.side_effect = lambda: (
                                order.append("serve"),
                                0,
                            )[1]

                            self.assertEqual(main(), 0)

        self.assertEqual(order, ["limits", "network", "serve"])

    def test_main_fails_closed_when_filesystem_isolation_cannot_be_enforced(self) -> None:
        expected_root = self.plugin_root.resolve()
        with patch.object(
            sys, "argv", ["plugin_worker.py", "--plugin-root", str(expected_root)]
        ):
            with patch.object(sys, "path", list(sys.path)):
                with patch(
                    "runtime.plugin_worker.isolate_worker_filesystem",
                    side_effect=WorkerFilesystemIsolationError("denied"),
                ):
                    with patch("runtime.plugin_worker.PluginWorkerServer") as server:
                        self.assertEqual(main(), 2)

        server.assert_not_called()

    def test_main_isolates_filesystem_before_loading_or_serving(self) -> None:
        expected_root = self.plugin_root.resolve()
        order: list[str] = []
        with patch.object(
            sys, "argv", ["plugin_worker.py", "--plugin-root", str(expected_root)]
        ):
            with patch.object(sys, "path", list(sys.path)):
                with patch(
                    "runtime.plugin_worker.apply_worker_resource_limits",
                    side_effect=lambda: order.append("limits"),
                ):
                    with patch(
                        "runtime.plugin_worker.isolate_worker_network",
                        side_effect=lambda: order.append("network"),
                    ):
                        with patch(
                            "runtime.plugin_worker.isolate_worker_filesystem",
                            side_effect=lambda _root: order.append("filesystem"),
                        ):
                            with patch("runtime.plugin_worker.PluginWorkerServer") as server:
                                server.return_value.serve.side_effect = lambda: (
                                    order.append("serve"),
                                    0,
                                )[1]

                                self.assertEqual(main(), 0)

        self.assertEqual(order, ["limits", "network", "filesystem", "serve"])

    def test_worker_imports_only_after_valid_load_and_keeps_module_state(self) -> None:
        worker = self._worker_for(
            "COUNTER = 0\n"
            "def activate(api):\n"
            "    global COUNTER\n"
            "    COUNTER += 1\n"
            "def deactivate():\n"
            "    assert COUNTER == 1\n"
        )

        self.assertEqual(worker.hello().to_dict()["kind"], "hello")
        self.assertTrue(worker.request(load_request()).success)
        self.assertEqual(worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-2")).status, "enabled")
        self.assertEqual(worker.request(lifecycle_request(LifecycleAction.DEACTIVATE, "request-3")).status, "disabled")

    def test_worker_rejects_lifecycle_before_load_without_importing_plugin(self) -> None:
        worker = self._worker_for("raise AssertionError('plugin must not import')\n")

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-activate"))

        self.assertFalse(result.success)
        self.assertEqual(result.status, "error")
        self.assertIsNone(worker.module)

    def test_worker_accepts_only_relative_regular_entrypoint_under_plugin_root(self) -> None:
        worker = self._worker_for("VALUE = 1\n")
        invalid = PluginLifecycleRequest(
            request_id="request-invalid",
            plugin_id=PLUGIN_ID,
            action=LifecycleAction.LOAD,
            payload=PluginLoadSpec(
                entry_point="../outside.py",
                permissions=(),
                api_version="1.0.0",
                generation=1,
            ).to_dict(),
        )

        result = worker.request(invalid)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "error")
        self.assertIsNone(worker.module)

    def test_worker_module_name_is_scoped_to_plugin_id_and_generation(self) -> None:
        first = self._worker_for("VALUE = 1\n")
        self.assertTrue(first.request(load_request(generation=1)).success)

        second = self._worker_for("VALUE = 2\n")
        self.assertTrue(second.request(load_request(generation=2)).success)

        self.assertNotEqual(first.module.__name__, second.module.__name__)
        self.assertIn(PLUGIN_ID.encode("utf-8").hex(), first.module.__name__)
        self.assertIn("generation_1", first.module.__name__)
        self.assertIn("generation_2", second.module.__name__)

    def test_module_names_use_reversible_id_encoding_without_collisions(self) -> None:
        first = self._worker_for("VALUE = 1\n")
        second = self._worker_for("VALUE = 2\n")

        self.assertTrue(first.request(load_request(plugin_id="a-b")).success)
        self.assertTrue(second.request(load_request(plugin_id="a.b")).success)

        self.assertNotEqual(first.module.__name__, second.module.__name__)
        self.assertIn("612d62", first.module.__name__)
        self.assertIn("612e62", second.module.__name__)

    def test_missing_deactivate_is_a_successful_disabled_noop(self) -> None:
        worker = self._worker_for("def activate(api):\n    pass\n")
        self.assertTrue(worker.request(load_request()).success)
        self.assertTrue(worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-activate")).success)

        result = worker.request(lifecycle_request(LifecycleAction.DEACTIVATE, "request-deactivate"))

        self.assertTrue(result.success)
        self.assertEqual(result.status, "disabled")

    def test_worker_converts_import_lifecycle_and_system_exit_to_results(self) -> None:
        import_worker = self._worker_for("raise RuntimeError('import failure')\n")
        self.assertFalse(import_worker.request(load_request()).success)

        exception_worker = self._worker_for("def activate(api):\n    raise RuntimeError('activation failure')\n")
        self.assertTrue(exception_worker.request(load_request()).success)
        self.assertFalse(
            exception_worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-exception")).success
        )

        exit_worker = self._worker_for("def activate(api):\n    raise SystemExit(17)\n")
        self.assertTrue(exit_worker.request(load_request()).success)
        exit_result = exit_worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-exit"))
        self.assertFalse(exit_result.success)
        self.assertEqual(exit_result.status, "error")

    def test_child_api_waits_for_matching_broker_result(self) -> None:
        broker_result = PluginBrokerResult(
            request_id="request-activate",
            call_id="call-1",
            plugin_id=PLUGIN_ID,
            allowed=True,
            result={"published": True},
            error="",
        )
        stdin = io.BytesIO(encode_message(broker_result))
        worker = self._worker_for(
            "def activate(api):\n"
            "    result = api.emit_event('plugin.activated', {'plugin_id': api.plugin_id})\n"
            "    assert result == {'published': True}\n",
            stdin=stdin,
        )
        self.assertTrue(worker.request(load_request()).success)

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-activate"))

        self.assertTrue(result.success)
        lines = worker.stdout.getvalue().splitlines(keepends=True)
        broker_request = decode_message(lines[-1])
        self.assertEqual(broker_request.to_dict()["kind"], "broker_request")
        self.assertEqual(broker_request.request_id, "request-activate")
        self.assertEqual(broker_request.call_id, "call-1")

    def test_child_api_rejects_nonmatching_broker_result(self) -> None:
        wrong_result = PluginBrokerResult(
            request_id="wrong-request",
            call_id="call-1",
            plugin_id=PLUGIN_ID,
            allowed=False,
            result=None,
            error="request_mismatch",
        )
        worker = self._worker_for(
            "def activate(api):\n"
            "    api.emit_event('plugin.activated', {})\n",
            stdin=io.BytesIO(encode_message(wrong_result)),
        )
        self.assertTrue(worker.request(load_request()).success)

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-activate"))

        self.assertFalse(result.success)
        self.assertEqual(result.status, "error")

    def test_child_api_denial_is_a_stable_lifecycle_error(self) -> None:
        denied_result = PluginBrokerResult(
            request_id="request-activate",
            call_id="call-1",
            plugin_id=PLUGIN_ID,
            allowed=False,
            result=None,
            error="capability_not_supported",
        )
        worker = self._worker_for(
            "def activate(api):\n"
            "    api.get_config('theme')\n",
            stdin=io.BytesIO(encode_message(denied_result)),
        )
        self.assertTrue(worker.request(load_request()).success)

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-activate"))

        self.assertFalse(result.success)
        self.assertEqual(result.error, "PLUGIN_BROKER_DENIED")

    def test_server_exits_after_an_invalid_wire_message(self) -> None:
        stdout = io.BytesIO()
        server = PluginWorkerServer(
            stdin=io.BytesIO(b"not-json\n"),
            stdout=stdout,
            stderr=io.StringIO(),
            plugin_root=self.plugin_root,
        )

        self.assertEqual(server.serve(), 1)
        self.assertEqual(decode_message(stdout.getvalue()), server.hello())

    def test_server_bounds_protocol_line_reads_before_decoding(self) -> None:
        class RecordingBytesIO(io.BytesIO):
            def __init__(self, value: bytes) -> None:
                super().__init__(value)
                self.read_sizes: list[int] = []

            def readline(self, size: int = -1) -> bytes:
                self.read_sizes.append(size)
                return super().readline(size)

        stdin = RecordingBytesIO(
            b"{" + b" " * MAX_PLUGIN_WORKER_LINE_BYTES + b"}\n"
        )
        server = PluginWorkerServer(
            stdin=stdin,
            stdout=io.BytesIO(),
            stderr=io.StringIO(),
            plugin_root=self.plugin_root,
        )

        self.assertEqual(server.serve(), 1)
        self.assertEqual(stdin.read_sizes, [MAX_PLUGIN_WORKER_LINE_BYTES + 1])

    def test_worker_import_and_serve_do_not_construct_legacy_sdk_services(self) -> None:
        source_root = Path(__file__).parent.parent / "src"
        with tempfile.TemporaryDirectory(prefix=".test-worker-cwd-") as cwd:
            script = (
                "import io, sys\n"
                f"sys.path.insert(0, {str(source_root)!r})\n"
                "from pathlib import Path\n"
                "from runtime.plugin_worker import PluginWorkerServer\n"
                "assert 'core.kernel.plugin_sdk' not in sys.modules\n"
                "assert not (Path.cwd() / 'plugins').exists()\n"
                "server = PluginWorkerServer(io.BytesIO(), io.BytesIO(), io.StringIO(), Path.cwd())\n"
                "assert server.serve() == 0\n"
                "assert 'core.kernel.plugin_sdk' not in sys.modules\n"
                "assert not (Path.cwd() / 'plugins').exists()\n"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", script],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_serve_writes_one_result_for_full_lifecycle_sequence(self) -> None:
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n    pass\n"
            "def deactivate():\n    pass\n"
            "def cleanup():\n    pass\n",
            encoding="utf-8",
        )
        requests = (
            load_request(),
            lifecycle_request(LifecycleAction.ACTIVATE, "request-activate"),
            lifecycle_request(LifecycleAction.DEACTIVATE, "request-deactivate"),
            lifecycle_request(LifecycleAction.CLEANUP, "request-cleanup"),
            lifecycle_request(LifecycleAction.SHUTDOWN, "request-shutdown"),
        )
        stdout = io.BytesIO()
        server = PluginWorkerServer(
            stdin=io.BytesIO(b"".join(encode_message(request) for request in requests)),
            stdout=stdout,
            stderr=io.StringIO(),
            plugin_root=self.plugin_root,
        )

        self.assertEqual(server.serve(), 0)
        messages = [decode_message(line) for line in stdout.getvalue().splitlines(keepends=True)]
        self.assertEqual([message.to_dict()["kind"] for message in messages], ["hello"] + ["lifecycle_result"] * 5)
        self.assertEqual([message.status for message in messages[1:]], ["loaded", "enabled", "disabled", "unloaded", "unloaded"])
        self.assertTrue(all(message.success for message in messages[1:]))

    def test_serve_returns_bounded_result_for_cleanup_exception(self) -> None:
        (self.plugin_root / "plugin.py").write_text(
            "def cleanup():\n    raise RuntimeError('cleanup failure')\n",
            encoding="utf-8",
        )
        stdout = io.BytesIO()
        server = PluginWorkerServer(
            stdin=io.BytesIO(
                encode_message(load_request())
                + encode_message(lifecycle_request(LifecycleAction.CLEANUP, "request-cleanup"))
            ),
            stdout=stdout,
            stderr=io.StringIO(),
            plugin_root=self.plugin_root,
        )

        self.assertEqual(server.serve(), 0)
        messages = [decode_message(line) for line in stdout.getvalue().splitlines(keepends=True)]
        self.assertTrue(messages[-1].success is False)
        self.assertEqual(messages[-1].status, "error")
        self.assertEqual(messages[-1].error, "plugin_lifecycle_failed: RuntimeError")

    def test_serve_returns_bounded_result_for_structurally_valid_wrong_broker_message(self) -> None:
        wrong_message = lifecycle_request(LifecycleAction.ACTIVATE, "request-wrong")
        (self.plugin_root / "plugin.py").write_text(
            "def activate(api):\n"
            "    api.emit_event('plugin.activated', {})\n",
            encoding="utf-8",
        )
        stdout = io.BytesIO()
        server = PluginWorkerServer(
            stdin=io.BytesIO(
                encode_message(load_request())
                + encode_message(lifecycle_request(LifecycleAction.ACTIVATE, "request-activate"))
                + encode_message(wrong_message)
            ),
            stdout=stdout,
            stderr=io.StringIO(),
            plugin_root=self.plugin_root,
        )

        self.assertEqual(server.serve(), 0)
        messages = [decode_message(line) for line in stdout.getvalue().splitlines(keepends=True)]
        self.assertFalse(messages[-1].success)
        self.assertEqual(messages[-1].status, "error")
        self.assertEqual(messages[-1].error, "plugin_lifecycle_failed: PluginWorkerProtocolError")

    def test_sdk_without_an_active_broker_fails_closed_with_stable_denial(self) -> None:
        api = XiaoYiPluginAPI(PLUGIN_ID, [])

        with self.assertRaisesRegex(PermissionError, "^PLUGIN_BROKER_DENIED$"):
            api.read_file("cannot-be-read.txt")

    def test_lifecycle_audit_is_bounded_when_plugin_makes_many_broker_calls(self) -> None:
        responses = b"".join(
            encode_message(
                PluginBrokerResult(
                    request_id="request-activate",
                    call_id=f"call-{index}",
                    plugin_id=PLUGIN_ID,
                    allowed=True,
                    result={"published": True},
                    error="",
                )
            )
            for index in range(1, 102)
        )
        worker = self._worker_for(
            "def activate(api):\n"
            "    for index in range(101):\n"
            "        api.emit_event('plugin.activated', {'index': index})\n",
            stdin=io.BytesIO(responses),
        )
        self.assertTrue(worker.request(load_request()).success)

        result = worker.request(lifecycle_request(LifecycleAction.ACTIVATE, "request-activate"))

        self.assertTrue(result.success)
        self.assertLessEqual(len(result.audit), 100)


if __name__ == "__main__":
    unittest.main()
