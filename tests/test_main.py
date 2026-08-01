"""
Unit tests for JARVISHandler methods in main.py
Tests helper methods (_send_json, _send_error, _read_body, _cors),
do_GET routing, do_POST routing, and individual handle_* methods
using unittest.mock - no live HTTP server required.
"""
import io
import http.client
import json
import os
import sys
import threading
import unittest
import warnings
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.kernel.capability_manifest import (  # noqa: E402
    CapabilityHealth,
    CapabilityKind,
    CapabilityLifecycle,
    CapabilityRecord,
    CapabilityRisk,
    CapabilitySnapshot,
)
from core.kernel.capability_resolver import (  # noqa: E402
    CapabilityQuery,
    CapabilityResolver,
    CompatibilityTarget,
)
from core.kernel.plugin_sdk import PluginManifest  # noqa: E402


def _load_main():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "main_unit_test",
        str(Path(__file__).parent.parent / "src" / "main.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_main = _load_main()
JARVISHandler = _main.JARVISHandler


def _make_handler(command="GET", path="/api/health", headers=None):
    handler = object.__new__(JARVISHandler)
    handler.command = command
    handler.path = path
    handler.requestline = f"{command} {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.headers = headers or {}
    handler.wfile = MagicMock()
    handler.rfile = io.BytesIO(b"")
    handler.server = MagicMock()
    handler.close_connection = False
    handler.protocol_version = "HTTP/1.1"
    handler.log_message = MagicMock()
    return handler


def _capability_snapshot(issues=()):
    records = (
        CapabilityRecord.create(
            capability_id="skill:memory-keeper",
            kind=CapabilityKind.SKILL,
            name="Memory Keeper",
            version=None,
            description="Local memory management",
            relative_path="skills/memory-keeper",
            entrypoint="skills/memory-keeper/SKILL.md",
            lifecycle=CapabilityLifecycle.DISCOVERED,
            permissions=("memory.read",),
            compatibility={"python": ">=3.10", "jarvis_api": ">=1.0"},
            source_url="https://example.invalid/memory-keeper",
            license_name="MIT",
            sha256="a" * 64,
            provenance_status="verified",
            health=CapabilityHealth.HEALTHY,
            risk=CapabilityRisk.LOW,
        ),
        CapabilityRecord.create(
            capability_id="plugin:event-logger",
            kind=CapabilityKind.PLUGIN,
            name="Event Logger",
            version="1.0.0",
            description="Records local events",
            relative_path="plugins/event-logger",
            entrypoint="plugins/event-logger/plugin.py",
            lifecycle=CapabilityLifecycle.DISABLED,
            permissions=("events.read",),
            source_url="https://example.invalid/event-logger",
            license_name="Apache-2.0",
            sha256="b" * 64,
            provenance_status="complete",
            health=CapabilityHealth.DEGRADED,
            health_issues=("disabled",),
            risk=CapabilityRisk.MEDIUM,
            risk_reasons=("event_access",),
        ),
    )
    return CapabilitySnapshot.create(records, issues)


def _capability_state(snapshot=None, error=None):
    registry = MagicMock()
    if error is None:
        registry.snapshot.return_value = snapshot or _capability_snapshot()
    else:
        registry.snapshot.side_effect = error
    return SimpleNamespace(
        capability_registry=registry,
        capability_resolver=CapabilityResolver(),
        capability_target=CompatibilityTarget(
            python="3.13.0",
            jarvis_api="1.1.0",
        ),
    )


def _prepare_json_handler(path):
    handler = _make_handler(path=path)
    for attr in ["send_response", "send_header", "end_headers", "wfile"]:
        setattr(handler, attr, MagicMock())
    return handler


class _FakeRoleTasks:
    def __init__(self, order=None, failures=0):
        self.order = order
        self.failures = failures
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        if self.order is not None:
            self.order.append("role_tasks")
        if self.shutdown_calls <= self.failures:
            raise RuntimeError("worker shutdown failed")


class _FakeRoleDispatch:
    def __init__(self, supervisor, results=None, errors=None):
        self.supervisor = supervisor
        self.results = results or {}
        self.errors = errors or {}
        self.calls = []

    def dispatch_by_role(self, role_name, prompt, timeout):
        self.calls.append(("role", role_name, prompt, timeout))
        if "role" in self.errors:
            raise self.errors["role"]
        return self.results["role"]

    def dispatch_by_capability(self, capability, prompt, timeout):
        self.calls.append(("capability", capability, prompt, timeout))
        if "capability" in self.errors:
            raise self.errors["capability"]
        return self.results["capability"]

    def batch_dispatch(self, tasks):
        self.calls.append(("batch", tasks))
        return self.results["batch"]


class _FakeHTTPState:
    def __init__(self, role_dispatch=None):
        self.role_dispatch = role_dispatch
        self.agent_factory = MagicMock()
        self.role_registry = MagicMock()
        self.start_time = 1.0
        self.request_count = 0

    def increment_requests(self):
        self.request_count += 1


@contextmanager
def _running_http_server(app_state):
    server = _main.create_http_server("127.0.0.1", 0, app_state=app_state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _http_json(address, method, path, payload=None):
    connection = http.client.HTTPConnection(*address, timeout=2)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


class TestMainHTTPHelpers(unittest.TestCase):
    def test_normalize_dispatch_text_accepts_surrogate_pair_and_scalar(self):
        paired_surrogates = "\ud83d\ude00"
        scalar_emoji = "\U0001f600"

        self.assertEqual(
            _main._normalize_dispatch_text(paired_surrogates),
            scalar_emoji,
        )
        self.assertEqual(
            _main._normalize_dispatch_text(scalar_emoji),
            scalar_emoji,
        )

    def test_send_json_sets_content_type(self):
        handler = _make_handler()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler._send_json({"key": "val"}, status=200)
        handler.send_response.assert_called_once_with(200)
        ct_calls = [c for c in handler.send_header.call_args_list if c[0][0] == "Content-Type"]
        self.assertEqual(len(ct_calls), 1)
        self.assertIn("application/json", ct_calls[0][0][1])

    def test_send_json_advertises_connection_close_when_required(self):
        handler = _make_handler()
        handler.close_connection = True
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler._send_json({"error": {"code": "fixture", "message": "fixture"}}, 413)

        self.assertIn(
            ("Connection", "close"),
            [call.args for call in handler.send_header.call_args_list],
        )

    def test_send_json_sets_cors_headers(self):
        handler = _make_handler(headers={"Origin": "http://localhost:5173"})
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler._send_json({"ok": True})
        hnames = [c[0][0] for c in handler.send_header.call_args_list]
        self.assertIn("Access-Control-Allow-Origin", hnames)
        self.assertIn("Access-Control-Allow-Methods", hnames)

    def test_send_json_uses_allowed_origin_from_env(self):
        previous = os.environ.get("JARVIS_ALLOWED_ORIGINS")
        os.environ["JARVIS_ALLOWED_ORIGINS"] = "http://localhost:5173,https://jarvis.local"
        try:
            handler = _make_handler(headers={"Origin": "https://jarvis.local"})
            handler.send_response = MagicMock()
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()
            handler.wfile = MagicMock()

            handler._send_json({"ok": True})

            origin_calls = [
                c for c in handler.send_header.call_args_list
                if c[0][0] == "Access-Control-Allow-Origin"
            ]
            self.assertEqual(origin_calls[0][0][1], "https://jarvis.local")
        finally:
            if previous is None:
                os.environ.pop("JARVIS_ALLOWED_ORIGINS", None)
            else:
                os.environ["JARVIS_ALLOWED_ORIGINS"] = previous

    def test_default_cors_origins_are_local_only(self):
        with patch.dict(os.environ, {"JARVIS_ALLOWED_ORIGINS": ""}):
            self.assertEqual(
                _main._configured_allowed_origins(),
                ["http://localhost:5173", "http://127.0.0.1:5173"],
            )

    def test_send_json_omits_disallowed_origin(self):
        previous = os.environ.get("JARVIS_ALLOWED_ORIGINS")
        os.environ["JARVIS_ALLOWED_ORIGINS"] = "https://jarvis.local"
        try:
            handler = _make_handler(headers={"Origin": "https://evil.example"})
            handler.send_response = MagicMock()
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()
            handler.wfile = MagicMock()

            handler._send_json({"ok": True})

            origin_calls = [
                c for c in handler.send_header.call_args_list
                if c[0][0] == "Access-Control-Allow-Origin"
            ]
            self.assertEqual(origin_calls, [])
        finally:
            if previous is None:
                os.environ.pop("JARVIS_ALLOWED_ORIGINS", None)
            else:
                os.environ["JARVIS_ALLOWED_ORIGINS"] = previous

    def test_send_json_writes_body(self):
        handler = _make_handler()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler._send_json({"status": "healthy", "version": "1.0.0"})
        handler.wfile.write.assert_called_once()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["status"], "healthy")

    def test_send_json_custom_status(self):
        handler = _make_handler()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler._send_json({"error": "bad"}, status=400)
        handler.send_response.assert_called_with(400)

    def test_send_json_content_length_correct(self):
        handler = _make_handler()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        test_data = {"msg": "hi"}
        handler._send_json(test_data, status=201)
        cl_calls = [c for c in handler.send_header.call_args_list if c[0][0] == "Content-Length"]
        self.assertEqual(len(cl_calls), 1)
        expected_len = len(json.dumps(test_data, ensure_ascii=False, indent=2).encode("utf-8"))
        self.assertEqual(int(cl_calls[0][0][1]), expected_len)

    def test_send_error_delegates_to_send_json(self):
        handler = _make_handler()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler._send_error("Not Found", status=404)
        handler.wfile.write.assert_called_once()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"], {
            "code": "HTTP_404",
            "message": "Not Found",
        })

    def test_send_error_default_status_400(self):
        handler = _make_handler()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        handler._send_error("bad request")
        handler.send_response.assert_called_with(400)

    def test_read_body_with_content(self):
        body = json.dumps({"model": "llama3", "prompt": "hello"}).encode("utf-8")
        handler = _make_handler()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        result = handler._read_body()
        self.assertEqual(result["model"], "llama3")
        self.assertEqual(result["prompt"], "hello")

    def test_read_body_uses_bounded_chunks(self):
        class BoundedChunkReader(io.BytesIO):
            def __init__(self, value):
                super().__init__(value)
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                if size > 8 * 1024:
                    raise AssertionError(f"unbounded read: {size}")
                return super().read(size)

        body = json.dumps({"value": "x" * 9000}).encode("utf-8")
        reader = BoundedChunkReader(body)
        handler = _make_handler()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = reader

        result = handler._read_body()

        self.assertEqual(result["value"], "x" * 9000)
        self.assertGreater(len(reader.read_sizes), 1)
        self.assertLessEqual(max(reader.read_sizes), 8 * 1024)
        self.assertFalse(handler.close_connection)

    def test_read_body_empty(self):
        handler = _make_handler()
        handler.headers = {"Content-Length": "0"}
        handler.rfile = io.BytesIO(b"")
        self.assertEqual(handler._read_body(), {})

    def test_read_body_no_content_length_header(self):
        handler = _make_handler()
        handler.headers = {}
        handler.rfile = io.BytesIO(b"")
        self.assertEqual(handler._read_body(), {})

    def test_read_body_invalid_json_raises_typed_error(self):
        handler = _make_handler()
        handler.headers = {"Content-Length": "5"}
        handler.rfile = io.BytesIO(b"not json")
        with self.assertRaises(_main.InvalidJsonBody):
            handler._read_body()

    def test_read_body_excessive_integer_raises_typed_error(self):
        body = b'{"value":' + (b"9" * 5000) + b"}"
        handler = _make_handler()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)

        with self.assertRaises(_main.InvalidJsonBody):
            handler._read_body()

    def test_read_body_deeply_nested_json_raises_typed_error(self):
        depth = 10_000
        body = b'{"value":' + (b"[" * depth) + b"0" + (b"]" * depth) + b"}"
        handler = _make_handler()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)

        with self.assertRaises(_main.InvalidJsonBody):
            handler._read_body()

    def test_read_body_short_read_raises_typed_error_and_closes_connection(self):
        handler = _make_handler()
        handler.headers = {"Content-Length": "3"}
        handler.rfile = io.BytesIO(b"{}")

        with self.assertRaises(_main.InvalidJsonBody):
            handler._read_body()

        self.assertTrue(handler.close_connection)

    def test_read_body_timeout_raises_typed_error_and_closes_connection(self):
        class TimeoutReader:
            def __init__(self):
                self.read_sizes = []

            def read(self, size):
                self.read_sizes.append(size)
                raise TimeoutError("fixture timeout")

        class FixtureConnection:
            def __init__(self):
                self.timeout = None
                self.timeout_values = []

            def gettimeout(self):
                return self.timeout

            def settimeout(self, value):
                self.timeout = value
                self.timeout_values.append(value)

        reader = TimeoutReader()
        connection = FixtureConnection()
        handler = _make_handler()
        handler.headers = {"Content-Length": "32"}
        handler.rfile = reader
        handler.connection = connection

        with self.assertRaises(_main.InvalidJsonBody):
            handler._read_body()

        self.assertTrue(handler.close_connection)
        self.assertEqual(reader.read_sizes, [32])
        active_timeouts = [
            value for value in connection.timeout_values if value is not None
        ]
        self.assertTrue(active_timeouts)
        self.assertLessEqual(max(active_timeouts), 2.0)
        self.assertIsNone(connection.timeout_values[-1])

    def test_read_body_discard_timeout_marks_connection_for_close(self):
        class TimeoutReader:
            def __init__(self):
                self.read_sizes = []

            def read(self, size):
                self.read_sizes.append(size)
                raise TimeoutError("fixture timeout")

        class FixtureConnection:
            def __init__(self):
                self.timeout = None
                self.timeout_values = []

            def gettimeout(self):
                return self.timeout

            def settimeout(self, value):
                self.timeout = value
                self.timeout_values.append(value)

        reader = TimeoutReader()
        connection = FixtureConnection()
        handler = _make_handler()
        handler.headers = {
            "Content-Length": str(_main.MAX_REQUEST_BODY_BYTES + 100),
        }
        handler.rfile = reader
        handler.connection = connection

        with self.assertRaises(_main.RequestBodyTooLarge):
            handler._read_body()

        self.assertTrue(handler.close_connection)
        self.assertTrue(reader.read_sizes)
        self.assertLessEqual(max(reader.read_sizes), 8 * 1024)
        self.assertTrue(any(value is not None for value in connection.timeout_values))
        self.assertIsNone(connection.timeout_values[-1])

    def test_cors_options_returns_204(self):
        handler = _make_handler(
            command="OPTIONS",
            path="/api/chat",
            headers={"Origin": "http://localhost:5173"},
        )
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        result = handler._cors()
        self.assertTrue(result)
        handler.send_response.assert_called_once_with(204)
        hnames = [c[0][0] for c in handler.send_header.call_args_list]
        self.assertIn("Access-Control-Allow-Origin", hnames)

    def test_cors_non_options_returns_false(self):
        handler = _make_handler(command="GET", path="/api/health")
        self.assertFalse(handler._cors())

    def test_log_message_is_callable(self):
        handler = _make_handler()
        self.assertTrue(callable(handler.log_message))


class TestMainHTTPGETRouting(unittest.TestCase):

    def _make_routed_handler(self, path, command="GET"):
        handler = _make_handler(command=command, path=path)
        handler._cors = MagicMock(return_value=False)
        return handler

    def test_do_get_calls_cors_first(self):
        handler = self._make_routed_handler("/api/health")
        handler.handle_health = MagicMock()
        handler.do_GET()
        handler._cors.assert_called_once()

    def test_do_get_health_routes(self):
        handler = self._make_routed_handler("/api/health")
        handler.handle_health = MagicMock()
        handler.do_GET()
        handler.handle_health.assert_called_once()

    def test_do_get_ollama_status_routes(self):
        handler = self._make_routed_handler("/api/ollama/status")
        handler.handle_ollama_status = MagicMock()
        handler.do_GET()
        handler.handle_ollama_status.assert_called_once()

    def test_do_get_ollama_models_routes(self):
        handler = self._make_routed_handler("/api/ollama/models")
        handler.handle_ollama_models = MagicMock()
        handler.do_GET()
        handler.handle_ollama_models.assert_called_once()

    def test_do_get_ollama_stream_routes(self):
        handler = self._make_routed_handler("/api/ollama/chat/stream")
        handler.handle_ollama_chat_stream = MagicMock()
        handler.do_GET()
        handler.handle_ollama_chat_stream.assert_called_once()

    def test_do_get_ollama_stream_with_query_routes(self):
        handler = self._make_routed_handler(
            "/api/ollama/chat/stream?model=fixture-model"
        )
        handler.handle_ollama_chat_stream = MagicMock()
        handler.do_GET()
        handler.handle_ollama_chat_stream.assert_called_once()

    def test_do_get_plugins_list_routes(self):
        handler = self._make_routed_handler("/api/plugins")
        handler.handle_plugins_list = MagicMock()
        handler.do_GET()
        handler.handle_plugins_list.assert_called_once()

    def test_do_get_capability_registry_routes_with_query(self):
        handler = self._make_routed_handler(
            "/api/capabilities/registry?q=memory&limit=5"
        )
        handler.handle_capabilities_registry = MagicMock()
        handler.do_GET()
        handler.handle_capabilities_registry.assert_called_once()

    def test_do_get_memory_entries_routes(self):
        handler = self._make_routed_handler("/api/memory/entries")
        handler.handle_memory_entries = MagicMock()
        handler.do_GET()
        handler.handle_memory_entries.assert_called_once()

    def test_do_get_events_routes(self):
        handler = self._make_routed_handler("/api/events")
        handler.handle_events = MagicMock()
        handler.do_GET()
        handler.handle_events.assert_called_once()

    def test_do_get_orchestrator_agents_routes(self):
        handler = self._make_routed_handler("/api/orchestrator/agents")
        handler.handle_orchestrator_agents = MagicMock()
        handler.do_GET()
        handler.handle_orchestrator_agents.assert_called_once()

    def test_do_get_orchestrator_history_routes(self):
        handler = self._make_routed_handler("/api/orchestrator/history")
        handler.handle_orchestrator_history = MagicMock()
        handler.do_GET()
        handler.handle_orchestrator_history.assert_called_once()

    def test_do_get_roles_list_routes(self):
        handler = self._make_routed_handler("/api/roles")
        handler.handle_roles_list = MagicMock()
        handler.do_GET()
        handler.handle_roles_list.assert_called_once()

    def test_do_get_roles_list_with_capability_query_routes(self):
        handler = self._make_routed_handler("/api/roles?capability=coding")
        handler.handle_roles_list = MagicMock()
        handler.do_GET()
        handler.handle_roles_list.assert_called_once()

    def test_do_get_single_role_routes(self):
        handler = self._make_routed_handler("/api/roles/engineer")
        handler.handle_role_get = MagicMock()
        handler.do_GET()
        handler.handle_role_get.assert_called_once_with("engineer")

    def test_do_get_nested_role_path_is_404(self):
        handler = self._make_routed_handler("/api/roles/engineer/extra")
        handler._send_error = MagicMock()
        handler.do_GET()
        handler._send_error.assert_called_once()
        self.assertEqual(handler._send_error.call_args[0][1], 404)

    def test_do_get_token_usage_routes(self):
        handler = self._make_routed_handler("/api/ollama/token-usage")
        handler.handle_ollama_token_usage = MagicMock()
        handler.do_GET()
        handler.handle_ollama_token_usage.assert_called_once()

    def test_do_get_system_stats_routes(self):
        handler = self._make_routed_handler("/api/system/stats")
        handler.handle_system_stats = MagicMock()
        handler.do_GET()
        handler.handle_system_stats.assert_called_once()

    def test_do_get_unknown_path_404(self):
        handler = self._make_routed_handler("/api/nonexistent_xyz")
        handler._send_error = MagicMock()
        handler.do_GET()
        handler._send_error.assert_called_once()
        self.assertEqual(handler._send_error.call_args[0][1], 404)

    def test_do_get_cors_short_circuits(self):
        handler = self._make_routed_handler("/api/health")
        handler.handle_health = MagicMock()
        handler._cors = MagicMock(return_value=True)
        handler.do_GET()
        handler.handle_health.assert_not_called()


class TestMainHTTPPOSTRouting(unittest.TestCase):

    def _make_routed_handler(self, path, command="POST"):
        handler = _make_handler(command=command, path=path)
        handler.headers = {"Content-Length": "0"}
        handler.rfile = io.BytesIO(b"")
        handler._cors = MagicMock(return_value=False)
        return handler

    def test_do_post_calls_cors_first(self):
        handler = self._make_routed_handler("/api/ollama/chat")
        handler.handle_ollama_chat = MagicMock()
        handler.do_POST()
        handler._cors.assert_called_once()

    def test_do_post_ollama_chat_routes(self):
        handler = self._make_routed_handler("/api/ollama/chat")
        handler.handle_ollama_chat = MagicMock()
        handler.do_POST()
        handler.handle_ollama_chat.assert_called_once()

    def test_do_post_token_usage_routes(self):
        handler = self._make_routed_handler("/api/ollama/token-usage")
        handler.handle_ollama_token_usage = MagicMock()
        handler.do_POST()
        handler.handle_ollama_token_usage.assert_called_once()

    def test_do_post_terminal_execute_routes(self):
        handler = self._make_routed_handler("/api/terminal/execute")
        handler.handle_terminal_execute = MagicMock()
        handler.do_POST()
        handler.handle_terminal_execute.assert_called_once()

    def test_do_post_plugin_load_routes(self):
        handler = self._make_routed_handler("/api/plugins/load")
        handler.handle_plugin_load = MagicMock()
        handler.do_POST()
        handler.handle_plugin_load.assert_called_once()

    def test_do_post_plugin_enable_routes(self):
        handler = self._make_routed_handler("/api/plugins/enable")
        handler.handle_plugin_enable = MagicMock()
        handler.do_POST()
        handler.handle_plugin_enable.assert_called_once()

    def test_do_post_plugin_disable_routes(self):
        handler = self._make_routed_handler("/api/plugins/disable")
        handler.handle_plugin_disable = MagicMock()
        handler.do_POST()
        handler.handle_plugin_disable.assert_called_once()

    def test_do_post_memory_store_routes(self):
        handler = self._make_routed_handler("/api/memory/store")
        handler.handle_memory_store = MagicMock()
        handler.do_POST()
        handler.handle_memory_store.assert_called_once()

    def test_do_post_orchestrator_dispatch_routes(self):
        handler = self._make_routed_handler("/api/orchestrator/dispatch")
        handler.handle_orchestrator_dispatch = MagicMock()
        handler.do_POST()
        handler.handle_orchestrator_dispatch.assert_called_once()

    def test_do_post_role_dispatch_routes(self):
        handler = self._make_routed_handler("/api/roles/dispatch")
        handler.handle_role_dispatch = MagicMock()
        handler.do_POST()
        handler.handle_role_dispatch.assert_called_once()

    def test_do_post_role_dispatch_by_cap_routes(self):
        handler = self._make_routed_handler("/api/roles/dispatch_by_cap")
        handler.handle_role_dispatch_by_cap = MagicMock()
        handler.do_POST()
        handler.handle_role_dispatch_by_cap.assert_called_once()

    def test_do_post_role_batch_dispatch_routes(self):
        handler = self._make_routed_handler("/api/roles/batch_dispatch")
        handler.handle_role_batch_dispatch = MagicMock()
        handler.do_POST()
        handler.handle_role_batch_dispatch.assert_called_once()

    def test_do_post_excessive_integer_returns_invalid_json_without_disconnect(self):
        body = (
            b'{"agent_name":"analyzer","prompt":"ping","timeout":'
            + (b"9" * 5000)
            + b"}"
        )
        handler = self._make_routed_handler("/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler.do_POST()

        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args.args[0])
        self.assertEqual(parsed["error"]["code"], "INVALID_JSON")
        self.assertFalse(handler.close_connection)

    def test_do_post_deeply_nested_json_returns_invalid_json_without_disconnect(self):
        depth = 10_000
        body = (
            b'{"agent_name":"analyzer","prompt":"ping","nested":'
            + (b"[" * depth)
            + b"0"
            + (b"]" * depth)
            + b"}"
        )
        handler = self._make_routed_handler("/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler.do_POST()

        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args.args[0])
        self.assertEqual(parsed["error"]["code"], "INVALID_JSON")
        self.assertFalse(handler.close_connection)

    def test_do_post_oversized_body_discards_payload_before_413(self):
        body = b"x" * (_main.MAX_REQUEST_BODY_BYTES + 52)
        handler = self._make_routed_handler("/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler.do_POST()

        self.assertEqual(handler.rfile.tell(), len(body))
        self.assertFalse(handler.close_connection)
        handler.send_response.assert_called_once_with(413)
        parsed = json.loads(handler.wfile.write.call_args.args[0])
        self.assertEqual(parsed["error"]["code"], "REQUEST_BODY_TOO_LARGE")

    def test_do_post_unknown_path_404(self):
        handler = self._make_routed_handler("/api/unknown_post_xyz")
        handler._send_error = MagicMock()
        handler.do_POST()
        handler._send_error.assert_called_once()
        self.assertEqual(handler._send_error.call_args[0][1], 404)

    def test_do_post_cors_short_circuits(self):
        handler = self._make_routed_handler("/api/ollama/chat")
        handler.handle_ollama_chat = MagicMock()
        handler._cors = MagicMock(return_value=True)
        handler.do_POST()
        handler.handle_ollama_chat.assert_not_called()


class TestMainHTTPHandleMethodsRouting(unittest.TestCase):

    def test_handle_health_returns_healthy(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_health()
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["status"], "healthy")

    def test_handle_health_includes_version_and_uptime(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_health()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("version", parsed)
        self.assertIn("uptime", parsed)

    def test_handle_ollama_status_returns_dict(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_ollama_status()
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIsInstance(parsed, dict)

    def test_handle_ollama_models_returns_models_key(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_ollama_models()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("models", parsed)

    def test_handle_ollama_chat_reads_body(self):
        body_data = json.dumps({"model": "test", "messages": [{"role": "user", "content": "hi"}]}).encode()
        handler = _make_handler(command="POST", path="/api/ollama/chat")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_ollama_chat()
        handler.send_response.assert_called_once()

    def test_handle_ollama_stream_uses_nested_error_frame_without_done(self):
        handler = _make_handler(
            path="/api/ollama/chat/stream?model=fixture-model"
        )
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        with patch.object(
            _main.state.ollama,
            "stream_chat_generator",
            side_effect=RuntimeError("fixture failure"),
        ):
            handler.handle_ollama_chat_stream()

        payload = b"".join(
            call[0][0] for call in handler.wfile.write.call_args_list
        )
        self.assertIn(
            b'"error": {"code": "OLLAMA_STREAM_ERROR", "message": "fixture failure"}',
            payload,
        )
        self.assertNotIn(b"data: [DONE]", payload)

    def test_handle_terminal_execute_missing_command_400(self):
        body_data = json.dumps({}).encode()
        handler = _make_handler(command="POST", path="/api/terminal/execute")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_terminal_execute()
        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("error", parsed)

    def test_handle_terminal_execute_is_disabled_without_capability(self):
        body_data = json.dumps({"command": "echo", "args": ["blocked"]}).encode()
        handler = _make_handler(command="POST", path="/api/terminal/execute")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "false", "JARVIS_TERMINAL_TOKEN": ""},
        ), patch.object(_main.state.terminal, "execute") as execute:
            handler.handle_terminal_execute()

        execute.assert_not_called()
        handler.send_response.assert_called_once_with(403)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "TERMINAL_DISABLED")

    def test_handle_terminal_execute_rejects_an_invalid_capability_token(self):
        body_data = json.dumps({"command": "pwd", "args": []}).encode()
        handler = _make_handler(command="POST", path="/api/terminal/execute")
        handler.headers = {
            "Content-Length": str(len(body_data)),
            "X-Jarvis-Terminal-Token": "wrong-token",
        }
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "true", "JARVIS_TERMINAL_TOKEN": "test-token"},
        ), patch.object(_main.state.terminal, "execute") as execute:
            handler.handle_terminal_execute()

        execute.assert_not_called()
        handler.send_response.assert_called_once_with(401)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "TERMINAL_UNAUTHORIZED")

    def test_handle_plugins_list_returns_list(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_plugins_list()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("plugins", parsed)
        self.assertIsInstance(parsed["plugins"], list)

    def test_handle_capability_registry_filters_and_serializes_public_records(self):
        handler = _prepare_json_handler(
            "/api/capabilities/registry"
            "?q=memory&kind=skill&compatible_only=true&max_risk=low&limit=1"
        )
        handler.app_state = _capability_state()

        handler.handle_capabilities_registry()

        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(
            set(parsed),
            {"schema_version", "capabilities", "count", "issues"},
        )
        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(
            parsed["capabilities"][0]["capability_id"],
            "skill:memory-keeper",
        )
        self.assertEqual(
            parsed["capabilities"][0]["compatibility"]["status"],
            "compatible",
        )
        self.assertNotIn("match", parsed["capabilities"][0])
        self.assertEqual(parsed["issues"], [])
        self.assertNotIn(
            str(Path(__file__).parent.parent.resolve()),
            json.dumps(parsed),
        )

    def test_handle_capability_registry_rejects_non_scalar_or_invalid_queries(self):
        invalid_paths = (
            "/api/capabilities/registry?q=one&q=two",
            "/api/capabilities/registry?kind=archive",
            "/api/capabilities/registry?kind=skill&kind=plugin",
            "/api/capabilities/registry?compatible_only=1",
            "/api/capabilities/registry?max_risk=critical",
            "/api/capabilities/registry?limit=0",
            "/api/capabilities/registry?limit=101",
            "/api/capabilities/registry?limit=abc",
            f"/api/capabilities/registry?q={'x' * 257}",
            "/api/capabilities/registry?q%5B%5D=memory",
            "/api/capabilities/registry?root=C%3A%5Csecret",
        )
        for path in invalid_paths:
            with self.subTest(path=path):
                handler = _prepare_json_handler(path)
                handler.app_state = _capability_state()

                handler.handle_capabilities_registry()

                handler.send_response.assert_called_once_with(400)
                parsed = json.loads(handler.wfile.write.call_args[0][0])
                self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")
                handler.app_state.capability_registry.snapshot.assert_not_called()

    def test_handle_capability_registry_hides_unavailable_path_details(self):
        repository_root = Path(__file__).parent.parent.resolve()
        handler = _prepare_json_handler("/api/capabilities/registry")
        handler.app_state = _capability_state(
            error=OSError(f"cannot read {repository_root / 'skills'}")
        )

        handler.handle_capabilities_registry()

        handler.send_response.assert_called_once_with(503)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(
            parsed["error"]["code"],
            "CAPABILITY_REGISTRY_UNAVAILABLE",
        )
        self.assertNotIn(str(repository_root), json.dumps(parsed))

    def test_handle_capability_registry_reports_bounded_snapshot_issues(self):
        issues = tuple(f"skill_invalid:item-{index}:read_failed" for index in range(101))
        handler = _prepare_json_handler("/api/capabilities/registry")
        handler.app_state = _capability_state(
            snapshot=_capability_snapshot(issues),
        )

        handler.handle_capabilities_registry()

        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("issues", parsed)
        self.assertEqual(len(parsed["issues"]), 100)
        self.assertEqual(parsed["issues"][-1], "issues_truncated")

    def test_default_capability_registry_uses_the_repository_root(self):
        expected_root = Path(__file__).parent.parent.resolve()
        self.assertEqual(_main.state.capability_registry._root, expected_root)

    def test_default_capability_target_matches_the_plugin_sdk(self):
        manifest = PluginManifest(name="fixture", version="1.0.0", description="")
        self.assertEqual(
            _main.state.capability_target.jarvis_api,
            manifest.api_version,
        )

    def test_default_registry_keeps_first_party_plugins_compatible(self):
        matches = _main.state.capability_resolver.resolve(
            _main.state.capability_registry.snapshot(),
            CapabilityQuery(
                kind=CapabilityKind.PLUGIN,
                compatible_only=True,
                limit=100,
            ),
            _main.state.capability_target,
        )
        self.assertEqual(
            {match.record.capability_id for match in matches},
            {"plugin:event-logger", "plugin:plugin-template"},
        )

    def test_handle_memory_entries_returns_entries(self):
        handler = _make_handler()
        handler.headers = {}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_memory_entries()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("entries", parsed)

    def test_handle_memory_entries_with_type_header(self):
        handler = _make_handler()
        handler.headers = {"X-Memory-Type": "project"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_memory_entries()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("entries", parsed)

    def test_handle_memory_store_creates_entry(self):
        body_data = json.dumps({
            "type": "user", "title": "unit_test_main",
            "content": "test from handle_memory_store", "tags": ["test"],
        }).encode()
        handler = _make_handler(command="POST", path="/api/memory/store")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_memory_store()
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertTrue(parsed.get("success"))
        self.assertIn("path", parsed)
        self.assertIn("id", parsed)

    def test_handle_memory_delete_removes_only_requested_entry(self):
        body_data = json.dumps({"cleanup_token": "secret"}).encode()
        handler = _make_handler(
            command="DELETE",
            path="/api/memory/probes/project/probe123",
        )
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        with patch.object(
            _main.state.memory_store,
            "delete_probe",
            return_value=True,
        ) as delete:
            handler.do_DELETE()

        delete.assert_called_once_with(_main.MemoryType.PROJECT, "probe123", "secret")
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed, {"success": True, "id": "probe123"})

    def test_handle_events_returns_empty_list(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_events()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("events", parsed)
        self.assertIsInstance(parsed["events"], list)

    def test_handle_orchestrator_agents_returns_dict(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_orchestrator_agents()
        handler.send_response.assert_called_once()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("agents", parsed)

    def test_handle_orchestrator_dispatch_missing_agent(self):
        body_data = json.dumps({"prompt": "test"}).encode()
        handler = _make_handler(command="POST", path="/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_orchestrator_dispatch()
        handler.send_response.assert_called_once_with(400)

    def test_handle_orchestrator_dispatch_missing_prompt(self):
        body_data = json.dumps({"agent_name": "test_agent"}).encode()
        handler = _make_handler(command="POST", path="/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_orchestrator_dispatch()
        handler.send_response.assert_called_once_with(400)

    def test_do_post_orchestrator_dispatch_rejects_non_object_body(self):
        body_data = json.dumps(["analyzer", "ping"]).encode()
        handler = _make_handler(command="POST", path="/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        handler.do_POST()

        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_orchestrator_dispatch_requires_non_empty_strings(self):
        invalid_payloads = [
            {"agent_name": 1, "prompt": "ping"},
            {"agent_name": [], "prompt": "ping"},
            {"agent_name": "analyzer", "prompt": 1},
            {"agent_name": "analyzer", "prompt": []},
            {"agent_name": "", "prompt": "ping"},
            {"agent_name": "analyzer", "prompt": ""},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                body_data = json.dumps(payload).encode()
                handler = _make_handler(
                    command="POST",
                    path="/api/orchestrator/dispatch",
                )
                handler.headers = {"Content-Length": str(len(body_data))}
                handler.rfile = io.BytesIO(body_data)
                for attr in ["send_response", "send_header", "end_headers", "wfile"]:
                    setattr(handler, attr, MagicMock())

                handler.handle_orchestrator_dispatch()

                handler.send_response.assert_called_once_with(400)
                parsed = json.loads(handler.wfile.write.call_args[0][0])
                self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_orchestrator_dispatch_rejects_surrogate_code_points(self):
        invalid_payloads = [
            {"agent_name": "\ud800", "prompt": "ping"},
            {"agent_name": "analyzer\udfff", "prompt": "ping"},
            {"agent_name": "analyzer", "prompt": "\ud800"},
            {"agent_name": "analyzer", "prompt": "ping\udfff"},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=repr(payload)):
                body_data = json.dumps(payload).encode("ascii")
                handler = _make_handler(
                    command="POST",
                    path="/api/orchestrator/dispatch",
                )
                handler.headers = {"Content-Length": str(len(body_data))}
                handler.rfile = io.BytesIO(body_data)
                for attr in ["send_response", "send_header", "end_headers", "wfile"]:
                    setattr(handler, attr, MagicMock())

                with patch("builtins.print"), patch.object(
                    _main.state.orchestrator,
                    "dispatch",
                ) as dispatch:
                    dispatch.return_value.to_dict.return_value = {}
                    handler.handle_orchestrator_dispatch()

                dispatch.assert_not_called()
                handler.send_response.assert_called_once_with(400)
                parsed = json.loads(handler.wfile.write.call_args[0][0])
                self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_orchestrator_dispatch_rejects_invalid_option_types(self):
        invalid_payloads = [
            {"agent_name": "analyzer", "prompt": "ping", "timeout": "45"},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": True},
            {"agent_name": "analyzer", "prompt": "ping", "priority": "3"},
            {"agent_name": "analyzer", "prompt": "ping", "priority": False},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                body_data = json.dumps(payload).encode()
                handler = _make_handler(
                    command="POST",
                    path="/api/orchestrator/dispatch",
                )
                handler.headers = {"Content-Length": str(len(body_data))}
                handler.rfile = io.BytesIO(body_data)
                for attr in ["send_response", "send_header", "end_headers", "wfile"]:
                    setattr(handler, attr, MagicMock())

                handler.handle_orchestrator_dispatch()

                handler.send_response.assert_called_once_with(400)
                parsed = json.loads(handler.wfile.write.call_args[0][0])
                self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_orchestrator_dispatch_enforces_timeout_range(self):
        for timeout in (0, 301, 10**100, True):
            with self.subTest(timeout=timeout):
                body_data = json.dumps({
                    "agent_name": "analyzer",
                    "prompt": "ping",
                    "timeout": timeout,
                }).encode()
                handler = _make_handler(
                    command="POST",
                    path="/api/orchestrator/dispatch",
                )
                handler.headers = {"Content-Length": str(len(body_data))}
                handler.rfile = io.BytesIO(body_data)
                for attr in ["send_response", "send_header", "end_headers", "wfile"]:
                    setattr(handler, attr, MagicMock())

                with patch("builtins.print"), patch.object(
                    _main.state.orchestrator,
                    "dispatch",
                ) as dispatch:
                    dispatch.return_value.to_dict.return_value = {}
                    handler.handle_orchestrator_dispatch()

                dispatch.assert_not_called()
                handler.send_response.assert_called_once_with(400)
                parsed = json.loads(handler.wfile.write.call_args[0][0])
                self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_orchestrator_history_rejects_non_integer_query_limit(self):
        handler = _make_handler(
            command="GET",
            path="/api/orchestrator/history?limit=abc",
        )
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        with patch.object(_main.state.orchestrator, "collect") as collect:
            handler.handle_orchestrator_history()

        collect.assert_not_called()
        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_orchestrator_history_clamps_query_limit(self):
        for query, expected_limit in (("101", 100), ("0", 1)):
            with self.subTest(query=query):
                handler = _make_handler(
                    command="GET",
                    path=f"/api/orchestrator/history?limit={query}",
                )
                for attr in ["send_response", "send_header", "end_headers", "wfile"]:
                    setattr(handler, attr, MagicMock())

                with patch.object(
                    _main.state.orchestrator,
                    "collect",
                    return_value=[],
                ) as collect:
                    handler.handle_orchestrator_history()

                collect.assert_called_once_with(limit=expected_limit)
                handler.send_response.assert_called_once_with(200)

    def test_handle_orchestrator_dispatch_forwards_timeout_and_priority(self):
        body_data = json.dumps({
            "agent_name": "analyzer",
            "prompt": "ping",
            "timeout": 45,
            "priority": 3,
        }).encode()
        handler = _make_handler(command="POST", path="/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        with patch.object(_main.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {}
            handler.handle_orchestrator_dispatch()

        task = dispatch.call_args.args[0]
        self.assertEqual(task.timeout, 45)
        self.assertEqual(task.priority, 3)

    def test_handle_orchestrator_dispatch_defaults_timeout_to_contract_maximum(self):
        body_data = json.dumps({
            "agent_name": "analyzer",
            "prompt": "ping",
        }).encode()
        handler = _make_handler(command="POST", path="/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())

        with patch("builtins.print"), patch.object(
            _main.state.orchestrator,
            "dispatch",
        ) as dispatch:
            dispatch.return_value.to_dict.return_value = {}
            handler.handle_orchestrator_dispatch()

        task = dispatch.call_args.args[0]
        self.assertEqual(task.timeout, 300)
        handler.send_response.assert_called_once_with(200)



    def test_handle_roles_list_returns_roles_and_count(self):
        handler = _make_handler(path="/api/roles")
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_roles_list()
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("roles", parsed)
        self.assertIn("count", parsed)
        self.assertEqual(parsed["count"], len(parsed["roles"]))
        self.assertGreater(parsed["count"], 0)

    def test_handle_roles_list_filters_by_capability(self):
        handler = _make_handler(path="/api/roles?capability=coding")
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_roles_list()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        for role in parsed["roles"]:
            self.assertIn("coding", role["capabilities"])

    def test_handle_role_get_known_role_returns_profile(self):
        handler = _make_handler(path="/api/roles/engineer")
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_get("engineer")
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["role"]["name"], "engineer")

    def test_handle_role_get_unknown_role_returns_404(self):
        handler = _make_handler(path="/api/roles/nonexistent_role_xyz")
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_get("nonexistent_role_xyz")
        handler.send_response.assert_called_once_with(404)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "ROLE_NOT_FOUND")

    def test_handle_role_dispatch_valid_returns_result(self):
        body_data = json.dumps({
            "role_name": "engineer",
            "prompt": "write a test",
            "timeout": 30,
        }).encode()
        handler = _make_handler(command="POST", path="/api/roles/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_dispatch()
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["role_name"], "engineer")
        self.assertIn("status", parsed)

    def test_handle_role_dispatch_missing_role_name_returns_400(self):
        body_data = json.dumps({"prompt": "test"}).encode()
        handler = _make_handler(command="POST", path="/api/roles/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_dispatch()
        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_role_dispatch_unknown_role_returns_404(self):
        body_data = json.dumps({
            "role_name": "nonexistent_role_xyz",
            "prompt": "test",
        }).encode()
        handler = _make_handler(command="POST", path="/api/roles/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_dispatch()
        handler.send_response.assert_called_once_with(404)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "ROLE_NOT_FOUND")

    def test_handle_role_dispatch_enforces_timeout_range(self):
        body_data = json.dumps({
            "role_name": "engineer",
            "prompt": "test",
            "timeout": 9000,
        }).encode()
        handler = _make_handler(command="POST", path="/api/roles/dispatch")
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_dispatch()
        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_role_dispatch_by_cap_valid_returns_result(self):
        body_data = json.dumps({
            "capability": "coding",
            "prompt": "fix bug",
        }).encode()
        handler = _make_handler(
            command="POST",
            path="/api/roles/dispatch_by_cap",
        )
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_dispatch_by_cap()
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("status", parsed)

    def test_handle_role_dispatch_by_cap_unknown_returns_404(self):
        body_data = json.dumps({
            "capability": "nonexistent_cap_xyz",
            "prompt": "test",
        }).encode()
        handler = _make_handler(
            command="POST",
            path="/api/roles/dispatch_by_cap",
        )
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_dispatch_by_cap()
        handler.send_response.assert_called_once_with(404)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "CAPABILITY_NOT_FOUND")

    def test_handle_role_batch_dispatch_returns_results(self):
        body_data = json.dumps({
            "tasks": [
                {"role": "engineer", "prompt": "task 1"},
                {"capability": "code_review", "prompt": "task 2"},
            ]
        }).encode()
        handler = _make_handler(
            command="POST",
            path="/api/roles/batch_dispatch",
        )
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_batch_dispatch()
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["count"], 2)
        self.assertEqual(len(parsed["results"]), 2)

    def test_handle_role_batch_dispatch_rejects_non_list_tasks(self):
        body_data = json.dumps({"tasks": {"not": "a list"}}).encode()
        handler = _make_handler(
            command="POST",
            path="/api/roles/batch_dispatch",
        )
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_role_batch_dispatch()
        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["error"]["code"], "INVALID_REQUEST")

    def test_handle_ollama_token_usage_returns_dict(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_ollama_token_usage()
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("latest", parsed)
        self.assertIn("totals", parsed)
        self.assertIn("samples", parsed)
        self.assertIn("session_started_at", parsed)


class TestMainHTTPRoleDispatchWorkerAdapter(unittest.TestCase):
    @staticmethod
    def result(
        role_name="engineer",
        task_id="task-worker",
        status="success",
        message="done",
    ):
        from core.brain.agent_factory import DispatchResult

        return DispatchResult(role_name, task_id, status, message)

    def test_injected_role_and_capability_routes_forward_exact_arguments(self):
        role_tasks = _FakeRoleTasks()
        service = _FakeRoleDispatch(
            role_tasks,
            results={
                "role": self.result(),
                "capability": self.result("reviewer", "task-cap"),
            },
        )
        app_state = _FakeHTTPState(service)

        with _running_http_server(app_state) as address:
            role_status, role_body = _http_json(
                address,
                "POST",
                "/api/roles/dispatch",
                {
                    "role_name": "engineer",
                    "prompt": "write a test",
                    "timeout": 30,
                },
            )
            cap_status, cap_body = _http_json(
                address,
                "POST",
                "/api/roles/dispatch_by_cap",
                {
                    "capability": "coding",
                    "prompt": "review it",
                    "timeout": 19,
                },
            )

        self.assertEqual(role_status, 200)
        self.assertEqual(role_body, {
            "role_name": "engineer",
            "task_id": "task-worker",
            "status": "success",
            "message": "done",
        })
        self.assertEqual(cap_status, 200)
        self.assertEqual(cap_body, {
            "role_name": "reviewer",
            "task_id": "task-cap",
            "status": "success",
            "message": "done",
        })
        self.assertEqual(service.calls, [
            ("role", "engineer", "write a test", 30),
            ("capability", "coding", "review it", 19),
        ])
        app_state.agent_factory.dispatch_by_role.assert_not_called()
        app_state.agent_factory.dispatch_by_capability.assert_not_called()

    def test_unknown_role_and_capability_are_mapped_after_service_call(self):
        role_tasks = _FakeRoleTasks()
        service = _FakeRoleDispatch(
            role_tasks,
            results={
                "role": self.result(
                    "missing-role",
                    "",
                    "no_role",
                    "service owns selection",
                ),
                "capability": self.result(
                    "",
                    "",
                    "no_capability",
                    "service owns selection",
                ),
            },
        )
        app_state = _FakeHTTPState(service)
        app_state.role_registry.get.side_effect = AssertionError(
            "adapter registry precheck"
        )

        with _running_http_server(app_state) as address:
            role_status, role_body = _http_json(
                address,
                "POST",
                "/api/roles/dispatch",
                {"role_name": "missing-role", "prompt": "work"},
            )
            cap_status, cap_body = _http_json(
                address,
                "POST",
                "/api/roles/dispatch_by_cap",
                {"capability": "missing-cap", "prompt": "work"},
            )

        self.assertEqual(role_status, 404)
        self.assertEqual(role_body["error"]["code"], "ROLE_NOT_FOUND")
        self.assertEqual(cap_status, 404)
        self.assertEqual(
            cap_body["error"]["code"],
            "CAPABILITY_NOT_FOUND",
        )
        self.assertEqual(service.calls, [
            ("role", "missing-role", "work", 300),
            ("capability", "missing-cap", "work", 300),
        ])
        app_state.role_registry.get.assert_not_called()

    def test_single_routes_map_three_worker_failures_to_exact_503(self):
        from core.brain.role_dispatch_service import (
            RoleTaskTerminationUnconfirmedError,
            RoleWorkerInvalidResultError,
            RoleWorkerUnavailableError,
        )

        failures = (
            (
                RoleWorkerUnavailableError,
                "ROLE_WORKER_UNAVAILABLE",
                "Role worker is unavailable",
            ),
            (
                RoleTaskTerminationUnconfirmedError,
                "ROLE_TASK_TERMINATION_UNCONFIRMED",
                "Worker process termination is not confirmed",
            ),
            (
                RoleWorkerInvalidResultError,
                "ROLE_WORKER_INVALID_RESULT",
                "Role worker returned an invalid result",
            ),
        )
        routes = (
            (
                "role",
                "/api/roles/dispatch",
                {"role_name": "engineer", "prompt": "work"},
            ),
            (
                "capability",
                "/api/roles/dispatch_by_cap",
                {"capability": "coding", "prompt": "work"},
            ),
        )

        for method, route, payload in routes:
            for error_type, code, message in failures:
                with self.subTest(route=route, error=error_type.__name__):
                    role_tasks = _FakeRoleTasks()
                    service = _FakeRoleDispatch(
                        role_tasks,
                        errors={
                            method: error_type(
                                "engineer",
                                "task-failed",
                                message,
                            )
                        },
                    )
                    app_state = _FakeHTTPState(service)
                    with _running_http_server(app_state) as address:
                        status, body = _http_json(
                            address,
                            "POST",
                            route,
                            payload,
                        )

                    self.assertEqual(status, 503)
                    self.assertEqual(body, {
                        "error": {"code": code, "message": message}
                    })
                    self.assertEqual(len(service.calls), 1)

    def test_batch_forwards_once_and_preserves_positional_errors_as_200(self):
        tasks = [
            {"role": "engineer", "prompt": "first"},
            {"capability": "review", "prompt": "second"},
        ]
        role_tasks = _FakeRoleTasks()
        service = _FakeRoleDispatch(
            role_tasks,
            results={
                "batch": [
                    self.result(task_id="task-one"),
                    self.result(
                        "reviewer",
                        "task-two",
                        "error",
                        "Role worker is unavailable",
                    ),
                ]
            },
        )
        app_state = _FakeHTTPState(service)

        with _running_http_server(app_state) as address:
            status, body = _http_json(
                address,
                "POST",
                "/api/roles/batch_dispatch",
                {"tasks": tasks},
            )

        self.assertEqual(status, 200)
        self.assertEqual(service.calls, [("batch", tasks)])
        self.assertEqual(body, {
            "results": [
                {
                    "role_name": "engineer",
                    "task_id": "task-one",
                    "status": "success",
                    "message": "done",
                },
                {
                    "role_name": "reviewer",
                    "task_id": "task-two",
                    "status": "error",
                    "message": "Role worker is unavailable",
                },
            ],
            "count": 2,
        })
        app_state.agent_factory.batch_dispatch.assert_not_called()


class TestMainHTTPStateLifecycle(unittest.TestCase):
    def test_default_worker_receives_resolved_trusted_roots(self):
        supervisor = MagicMock()
        with patch.object(
            _main,
            "RoleWorkerSupervisor",
            return_value=supervisor,
        ) as supervisor_type:
            app_state = _main.AppState(terminal=MagicMock())
        try:
            runner_config = supervisor_type.call_args.kwargs["runner_config"]
            self.assertEqual(
                runner_config["memory_dir"],
                str((Path.cwd() / ".auto-memory").resolve()),
            )
            self.assertEqual(
                runner_config["repository_root"],
                str(Path.cwd().resolve()),
            )
        finally:
            app_state.shutdown()

    def test_run_server_shuts_down_injected_state_when_creation_fails(self):
        app_state = MagicMock()
        with patch.object(
            _main,
            "create_http_server",
            side_effect=OSError("bind failed"),
        ):
            with self.assertRaisesRegex(OSError, "bind failed"):
                _main.run_server(app_state=app_state)

        app_state.shutdown.assert_called_once_with()

    def test_create_http_server_does_not_leak_constructor_socket(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            server = _main.create_http_server("127.0.0.1", 0)
            server.server_close()

        resource_warnings = [
            warning
            for warning in caught
            if issubclass(warning.category, ResourceWarning)
        ]
        self.assertEqual(resource_warnings, [])

    def test_bound_server_uses_injected_state_without_mutating_default(self):
        default_state = _main.state
        injected_state = _FakeHTTPState()

        with _running_http_server(injected_state) as address:
            status, body = _http_json(address, "GET", "/api/health")

        self.assertEqual(status, 200)
        self.assertEqual(body["requests"], 1)
        self.assertEqual(injected_state.request_count, 1)
        self.assertIs(_main.state, default_state)
        self.assertIs(_main.JARVISHandler.app_state, default_state)

    def test_injected_dispatch_reuses_supervisor_and_mismatch_is_rejected(self):
        role_tasks = _FakeRoleTasks()
        role_dispatch = _FakeRoleDispatch(role_tasks)
        terminal = MagicMock()

        with patch.object(
            _main,
            "RoleWorkerSupervisor",
            side_effect=AssertionError("constructed a second supervisor"),
        ):
            app_state = _main.AppState(
                terminal=terminal,
                role_dispatch=role_dispatch,
            )
        try:
            self.assertIs(app_state.role_tasks, role_tasks)
            self.assertIs(app_state.role_dispatch, role_dispatch)
        finally:
            app_state.shutdown()

        with self.assertRaisesRegex(
            ValueError,
            "role_tasks and role_dispatch must share the same supervisor",
        ):
            _main.AppState(
                terminal=MagicMock(),
                role_tasks=_FakeRoleTasks(),
                role_dispatch=role_dispatch,
            )

    def test_shutdown_is_worker_first_and_idempotent(self):
        order = []
        role_tasks = _FakeRoleTasks(order)
        role_dispatch = _FakeRoleDispatch(role_tasks)
        terminal = MagicMock()
        terminal.close.side_effect = lambda: order.append("terminal")
        app_state = _main.AppState(
            terminal=terminal,
            role_tasks=role_tasks,
            role_dispatch=role_dispatch,
        )
        original_orchestrator_shutdown = app_state.orchestrator.shutdown

        def shutdown_orchestrator():
            order.append("orchestrator")
            original_orchestrator_shutdown()

        app_state.orchestrator.shutdown = shutdown_orchestrator
        app_state.agent_factory.shutdown = lambda: order.append("agent_factory")

        app_state.shutdown()
        app_state.shutdown()

        self.assertEqual(order, [
            "role_tasks",
            "orchestrator",
            "agent_factory",
            "terminal",
        ])
        self.assertEqual(role_tasks.shutdown_calls, 1)

    def test_shutdown_retries_only_failed_resources(self):
        order = []
        role_tasks = _FakeRoleTasks(order, failures=1)
        role_dispatch = _FakeRoleDispatch(role_tasks)
        terminal = MagicMock()
        terminal.close.side_effect = lambda: order.append("terminal")
        app_state = _main.AppState(
            terminal=terminal,
            role_tasks=role_tasks,
            role_dispatch=role_dispatch,
        )
        original_orchestrator_shutdown = app_state.orchestrator.shutdown

        def shutdown_orchestrator():
            order.append("orchestrator")
            original_orchestrator_shutdown()

        app_state.orchestrator.shutdown = shutdown_orchestrator
        app_state.agent_factory.shutdown = lambda: order.append("agent_factory")

        with self.assertRaisesRegex(RuntimeError, "worker shutdown failed"):
            app_state.shutdown()
        app_state.shutdown()
        app_state.shutdown()

        self.assertEqual(order, [
            "role_tasks",
            "orchestrator",
            "agent_factory",
            "terminal",
            "role_tasks",
        ])
        self.assertEqual(role_tasks.shutdown_calls, 2)

    def test_run_server_closes_server_and_active_state_from_finally(self):
        active_state = MagicMock()
        fake_server = MagicMock()
        fake_server.serve_forever.side_effect = KeyboardInterrupt
        default_state = _main.state

        with patch.object(
            _main,
            "create_http_server",
            return_value=fake_server,
        ) as create_server:
            _main.run_server("127.0.0.1", 0, app_state=active_state)

        create_server.assert_called_once_with(
            "127.0.0.1",
            0,
            app_state=active_state,
        )
        fake_server.shutdown.assert_called_once_with()
        fake_server.server_close.assert_called_once_with()
        active_state.shutdown.assert_called_once_with()
        self.assertIs(_main.state, default_state)

    def test_atexit_registers_state_shutdown(self):
        with patch("atexit.register") as register:
            module = _load_main()
        try:
            callback = register.call_args.args[0]
            self.assertIs(callback.__self__, module.state)
            self.assertIs(callback.__func__, type(module.state).shutdown)
        finally:
            cleanup = getattr(module.state, "shutdown", module.state.terminal.close)
            cleanup()

class TestMainHTTPEdgeCases(unittest.TestCase):

    def test_read_body_unicode_content(self):
        body_data = json.dumps({"content": chr(0x4e2d) + chr(0x6587) + " test"}).encode("utf-8")
        handler = _make_handler()
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        result = handler._read_body()
        self.assertIn("test", result["content"])

    def test_read_body_nested_json(self):
        body_data = json.dumps({"data": {"nested": {"key": "val"}, "list": [1, 2, 3]}, "count": 3}).encode("utf-8")
        handler = _make_handler()
        handler.headers = {"Content-Length": str(len(body_data))}
        handler.rfile = io.BytesIO(body_data)
        result = handler._read_body()
        self.assertEqual(result["data"]["nested"]["key"], "val")
        self.assertEqual(result["data"]["list"], [1, 2, 3])

    def test_send_json_unicode_data(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        test_data = {"name": chr(0x5c0f) + chr(0x5955), "desc": "test"}
        handler._send_json(test_data)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["name"], chr(0x5c0f) + chr(0x5955))

    def test_send_json_empty_dict(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler._send_json({})
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed, {})

    def test_cors_options_sets_all_required_headers(self):
        handler = _make_handler(
            command="OPTIONS",
            path="/api/test",
            headers={"Origin": "http://localhost:5173"},
        )
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler._cors()
        hnames = [c[0][0] for c in handler.send_header.call_args_list]
        required = ["Access-Control-Allow-Origin", "Access-Control-Allow-Methods",
                    "Access-Control-Allow-Headers"]
        for h in required:
            self.assertIn(h, hnames, f"Missing CORS header: {h}")




# Backwards compatibility aliases for test runner bookkeeping
TestJARVISHandlerHelpers = TestMainHTTPHelpers
TestJARVISHandlerDoGET = TestMainHTTPGETRouting
TestJARVISHandlerDoPOST = TestMainHTTPPOSTRouting
TestJARVISHandlerHandleMethods = TestMainHTTPHandleMethodsRouting
TestJARVISHandlerEdgeCases = TestMainHTTPEdgeCases

def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. JARVISHandler unit tests - Iteration 41")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestJARVISHandlerHelpers, TestJARVISHandlerDoGET,
               TestJARVISHandlerDoPOST, TestJARVISHandlerHandleMethods,
               TestJARVISHandlerEdgeCases]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print()
    print("=" * 60)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed, {len(result.failures)} failed, {len(result.errors)} errors")
    print("=" * 60)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
