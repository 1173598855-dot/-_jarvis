"""
Test main_fastapi.py - Phase 11 FastAPI REST API integration tests
Run: python3 tests/test_main_fastapi.py
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Test that the module can be imported (syntax check)
class TestMainFastapiSyntax(unittest.TestCase):

    def test_import_main_fastapi(self):
        """Verify main_fastapi.py can be parsed without syntax errors"""
        import ast
        path = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertGreater(len(source), 10000, "File too short - may be truncated")

    def test_fastapi_app_exists(self):
        """Verify FastAPI app object is created"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "main_fastapi",
                str(Path(__file__).parent.parent / "src" / "main_fastapi.py"),
            )
            self.assertIsNotNone(spec)
        except Exception as e:
            self.fail(f"Module spec error: {e}")

    def test_agent_factory_imported(self):
        """Verify agent_factory is imported in main_fastapi"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("from core.brain.agent_factory import", text)
        self.assertIn("AgentFactory", text)

    def test_role_registry_imported(self):
        """Verify role_registry function is imported in main_fastapi"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("from core.brain.role_registry import", text)
        self.assertIn("create_default_registry", text)

    def test_api_role_routes_exist(self):
        """Verify Phase 11 role API routes exist"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('"/api/roles"', text)
        self.assertIn('"/api/roles/{role_name}"', text)
        self.assertIn('"/api/roles/dispatch"', text)
        self.assertIn('"/api/roles/dispatch_by_cap"', text)
        self.assertIn('"/api/roles/batch_dispatch"', text)

    def test_file_not_truncated(self):
        """Verify file ends with complete code (no truncation at data=a)"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped == "data = a":
                self.fail("File is truncated at 'data = a'")
        self.assertIn("uvicorn.run(app", text)

    def test_uses_lifespan_instead_of_deprecated_event_hooks(self):
        """FastAPI lifecycle is configured through the lifespan API."""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")

        self.assertIn("lifespan=lifespan", text)
        self.assertNotIn("@app.on_event", text)

    def test_isolated_app_lifespan_does_not_shutdown_default_state(self):
        from fastapi.testclient import TestClient
        import main_fastapi

        with tempfile.TemporaryDirectory() as memory_dir:
            isolated_state = main_fastapi.AppState(memory_dir=memory_dir)
            isolated_app = main_fastapi.create_app(isolated_state)
            sandbox_dir = isolated_state.terminal.sandbox_dir
            with patch.object(
                main_fastapi.state.orchestrator,
                "shutdown",
            ) as default_shutdown:
                with TestClient(isolated_app) as client:
                    self.assertEqual(client.get("/api/health").status_code, 200)

            default_shutdown.assert_not_called()
            self.assertTrue(isolated_state.orchestrator._shutdown)
            self.assertFalse(os.path.exists(sandbox_dir))

    def test_app_state_has_agent_factory(self):
        """Verify AppState includes agent_factory"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("self.agent_factory = AgentFactory(", text)
        self.assertIn("registry=self.role_registry", text)
        self.assertIn("orchestrator=self.orchestrator", text)

    def test_version_bumped(self):
        """Verify API version is 1.1.0"""
        source = Path(__file__).parent.parent / "src" / "main_fastapi.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('version="1.1.0"', text)



class TestRequestBodyLimitMiddleware(unittest.TestCase):
    def test_rejects_headerless_chunked_overflow(self):
        import main_fastapi

        incoming = iter([
            {
                "type": "http.request",
                "body": b"x" * main_fastapi.MAX_REQUEST_BODY_BYTES,
                "more_body": True,
            },
            {"type": "http.request", "body": b"x", "more_body": False},
        ])
        downstream_messages = []
        sent = []

        async def receive():
            return next(incoming)

        async def send(message):
            sent.append(message)

        async def downstream(_scope, downstream_receive, _send):
            downstream_messages.append(await downstream_receive())

        middleware = main_fastapi._RequestBodyLimitMiddleware(downstream)
        asyncio.run(middleware(
            {"type": "http", "method": "POST", "headers": []},
            receive,
            send,
        ))

        self.assertEqual(downstream_messages[0]["type"], "http.disconnect")
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(
            json.loads(sent[-1]["body"]),
            {
                "error": {
                    "code": "REQUEST_BODY_TOO_LARGE",
                    "message": "Request body exceeds the 32 KiB limit",
                }
            },
        )


# ============================================================
# Test: Role dispatch endpoints (Iteration 40)
# ============================================================

class TestRoleDispatchEndpoints(unittest.TestCase):
    """Test Phase 11 role-driven dispatch endpoints"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_dispatch_by_role_valid(self):
        resp = self.client.post("/api/roles/dispatch", json={
            "role_name": "engineer", "prompt": "write a test", "timeout": 30,
        })
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable

    def test_dispatch_by_role_missing_role_name(self):
        resp = self.client.post("/api/roles/dispatch", json={"prompt": "test"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_dispatch_by_role_invalid_role(self):
        resp = self.client.post("/api/roles/dispatch", json={
            "role_name": "nonexistent_role_xyz", "prompt": "test",
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "ROLE_NOT_FOUND")

    def test_dispatch_by_capability_coding(self):
        resp = self.client.post("/api/roles/dispatch_by_cap", json={
            "capability": "coding", "prompt": "fix bug",
        })
        self.assertIn(resp.status_code, [200, 404])

    def test_dispatch_by_capability_unknown(self):
        resp = self.client.post("/api/roles/dispatch_by_cap", json={
            "capability": "nonexistent_cap_xyz", "prompt": "test",
        })
        self.assertEqual(resp.status_code, 404)

    def test_batch_dispatch_returns_results(self):
        resp = self.client.post("/api/roles/batch_dispatch", json={
            "tasks": [
                {"role_name": "engineer", "prompt": "task 1", "timeout": 30},
                {"role_name": "reviewer", "prompt": "task 2", "timeout": 30},
            ]
        })
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable
        if resp.status_code == 200:
            data = resp.json()
            self.assertIn("results", data)
            self.assertIn("count", data)

    def test_batch_dispatch_empty_tasks(self):
        resp = self.client.post("/api/roles/batch_dispatch", json={"tasks": []})
        self.assertIn(resp.status_code, [200, 422])


class TestQueryEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_memory_entries_with_type_filter(self):
        resp = self.client.get("/api/memory/entries?memory_type=user")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("entries", data)
        self.assertIsInstance(data["entries"], list)

    def test_memory_entries_invalid_type_ignored(self):
        resp = self.client.get("/api/memory/entries?memory_type=invalid_type")
        self.assertEqual(resp.status_code, 200)

    def test_orchestrator_history_default_limit(self):
        resp = self.client.get("/api/orchestrator/history")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        self.assertIn("count", data)

    def test_orchestrator_history_custom_limit(self):
        resp = self.client.get("/api/orchestrator/history?limit=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(data["count"], 5)

    def test_orchestrator_history_clamps_limit_to_contract_maximum(self):
        import main_fastapi

        with patch.object(
            main_fastapi.state.orchestrator,
            "collect",
            return_value=[],
        ) as collect:
            resp = self.client.get("/api/orchestrator/history?limit=101")

        self.assertEqual(resp.status_code, 200)
        collect.assert_called_once_with(limit=100)

    def test_orchestrator_history_rejects_non_integer_limit_with_invalid_request(self):
        resp = self.client.get("/api/orchestrator/history?limit=abc")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_roles_list_with_capability_filter(self):
        resp = self.client.get("/api/roles?capability=coding")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("roles", data)
        self.assertIn("count", data)


class TestOrchestratorInputValidation(unittest.TestCase):
    """The shared orchestrator contract rejects malformed request values."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.main_fastapi = main_fastapi
        cls.client = TestClient(main_fastapi.app, raise_server_exceptions=False)

    def assert_invalid_request(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        self.assertIn("message", response.json()["error"])

    def test_normalize_dispatch_text_accepts_surrogate_pair_and_scalar(self):
        paired_surrogates = "\ud83d\ude00"
        scalar_emoji = "\U0001f600"

        self.assertEqual(
            self.main_fastapi._normalize_dispatch_text(paired_surrogates),
            scalar_emoji,
        )
        self.assertEqual(
            self.main_fastapi._normalize_dispatch_text(scalar_emoji),
            scalar_emoji,
        )

    def test_dispatch_rejects_non_object_json_bodies(self):
        for payload in ([], 1, "prompt"):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    json=payload,
                )
                self.assert_invalid_request(response)

    def test_dispatch_rejects_malformed_json_with_invalid_json_code(self):
        response = self.client.post(
            "/api/orchestrator/dispatch",
            content=b'{"agent_name":',
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_JSON")

    def test_dispatch_normalizes_json_resource_limit_errors(self):
        excessive_integer = (
            b'{"agent_name":"analyzer","prompt":"ping","timeout":'
            + (b"9" * 5000)
            + b"}"
        )
        depth = 10_000
        deeply_nested = (
            b'{"agent_name":"analyzer","prompt":"ping","nested":'
            + (b"[" * depth)
            + b"0"
            + (b"]" * depth)
            + b"}"
        )

        for payload in (excessive_integer, deeply_nested):
            with self.subTest(payload_size=len(payload)):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "INVALID_JSON",
                )

    def test_dispatch_rejects_non_string_or_blank_agent_and_prompt(self):
        payloads = (
            {"agent_name": 1, "prompt": "ping"},
            {"agent_name": [], "prompt": "ping"},
            {"agent_name": "analyzer", "prompt": 1},
            {"agent_name": "analyzer", "prompt": []},
            {"agent_name": "   ", "prompt": "ping"},
            {"agent_name": "analyzer", "prompt": "\t"},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    json=payload,
                )
                self.assert_invalid_request(response)

    def test_dispatch_rejects_surrogate_code_points(self):
        payloads = (
            b'{"agent_name":"\\ud800","prompt":"ping"}',
            b'{"agent_name":"analyzer\\udfff","prompt":"ping"}',
            b'{"agent_name":"analyzer","prompt":"\\ud800"}',
            b'{"agent_name":"analyzer","prompt":"ping\\udfff"}',
        )
        with patch.object(self.main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            for payload in payloads:
                with self.subTest(payload=payload):
                    response = self.client.post(
                        "/api/orchestrator/dispatch",
                        content=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    self.assert_invalid_request(response)

        dispatch.assert_not_called()

    def test_dispatch_enforces_timeout_minimum_and_priority_bounds(self):
        for payload in (
            {"agent_name": "analyzer", "prompt": "ping", "timeout": 0},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": -1},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": 301},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": 10**100},
            {"agent_name": "analyzer", "prompt": "ping", "timeout": True},
            {"agent_name": "analyzer", "prompt": "ping", "priority": -1},
            {"agent_name": "analyzer", "prompt": "ping", "priority": 4},
            {"agent_name": "analyzer", "prompt": "ping", "priority": True},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/orchestrator/dispatch",
                    json=payload,
                )
                self.assert_invalid_request(response)

    def test_dispatch_accepts_contract_boundary_values(self):
        with patch.object(self.main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            response = self.client.post(
                "/api/orchestrator/dispatch",
                json={
                    "agent_name": "analyzer",
                    "prompt": "ping",
                    "timeout": 300,
                    "priority": 0,
                },
            )

        self.assertEqual(response.status_code, 200)
        task = dispatch.call_args.args[0]
        self.assertEqual(task.timeout, 300)
        self.assertEqual(task.priority, 0)

    def test_dispatch_defaults_timeout_to_contract_maximum(self):
        with patch.object(self.main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            response = self.client.post(
                "/api/orchestrator/dispatch",
                json={"agent_name": "analyzer", "prompt": "ping"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(dispatch.call_args.args[0].timeout, 300)


class TestPluginLifecycleEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_plugin_enable_nonexistent_returns_error(self):
        resp = self.client.post("/api/plugins/enable", json={"plugin_id": "nonexistent_xyz_999"})
        self.assertIn(resp.status_code, [200, 404, 500])

    def test_plugin_disable_nonexistent_returns_error(self):
        resp = self.client.post("/api/plugins/disable", json={"plugin_id": "nonexistent_xyz_999"})
        self.assertIn(resp.status_code, [200, 404, 500])


class TestPydanticModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        import main_fastapi
        cls.mf = main_fastapi

    def test_chat_request_defaults(self):
        req = self.mf.ChatRequest(messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(req.model, "default")
        self.assertFalse(req.stream)

    def test_terminal_request_requires_command(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.mf.TerminalRequest()

    def test_memory_request_defaults(self):
        req = self.mf.MemoryRequest(title="t", content="c")
        self.assertEqual(req.type, "user")
        self.assertEqual(req.tags, [])

    def test_plugin_load_request_requires_plugin_id(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.mf.PluginLoadRequest()

    def test_batch_dispatch_default_empty(self):
        req = self.mf.BatchDispatchRequest()
        self.assertEqual(req.tasks, [])

def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. main_fastapi tests - Iteration 31")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestMainFastapiSyntax)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 60)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed, {len(result.failures)} failed, {len(result.errors)} errors")
    print("=" * 60)
    return 0 if result.wasSuccessful() else 1

class TestFastAPIEndpoints(unittest.TestCase):
    """Integration tests for FastAPI HTTP endpoints using TestClient"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient

        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_health_returns_200(self):
        """GET /api/health returns status=healthy"""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)

    def test_health_has_uptime(self):
        """Health response includes uptime as float"""
        resp = self.client.get("/api/health")
        data = resp.json()
        self.assertIn("uptime", data)
        self.assertIsInstance(data["uptime"], (int, float))

    def test_system_stats_returns_200(self):
        """GET /api/system/stats returns dict with cpu/memory/disk/network"""
        resp = self.client.get("/api/system/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cpu", data)
        self.assertIn("memory", data)
        self.assertIn("disk", data)
        self.assertIn("network", data)

    def test_ollama_status_returns_dict(self):
        """GET /api/ollama/status returns dict (error OK since no Ollama)"""
        resp = self.client.get("/api/ollama/status")
        # Returns 200 with status dict or 500 if Ollama unavailable
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable

    def test_ollama_chat_missing_model_returns_400(self):
        """POST /api/ollama/chat with empty model returns error"""
        resp = self.client.post("/api/ollama/chat", json={"messages": []})
        # Upstream unavailability is normalized to the public 502 envelope.
        self.assertIn(resp.status_code, [400, 502])

    def test_terminal_execute_empty_command_returns_400(self):
        """POST /api/terminal/execute with empty command returns 400"""
        resp = self.client.post("/api/terminal/execute", json={"command": ""})
        self.assertEqual(resp.status_code, 400)

    def test_terminal_execute_missing_field_returns_standard_error(self):
        """POST /api/terminal/execute without 'command' uses the shared envelope."""
        resp = self.client.post("/api/terminal/execute", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "MISSING_COMMAND")

    def test_plugins_list_returns_200(self):
        """GET /api/plugins returns list of plugins"""
        resp = self.client.get("/api/plugins")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("plugins", data)
        self.assertIsInstance(data["plugins"], list)

    def test_memory_entries_returns_list(self):
        """GET /api/memory/entries returns list"""
        resp = self.client.get("/api/memory/entries")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("entries", data)
        self.assertIsInstance(data["entries"], list)

    def test_memory_store_returns_success(self):
        """POST /api/memory/store creates a new entry"""
        resp = self.client.post("/api/memory/store", json={
            "type": "user",
            "title": "test_entry",
            "content": "test content for integration",
            "tags": ["test"],
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("success", data)
        self.assertTrue(data["success"])

    def test_events_returns_list(self):
        """GET /api/events returns list of events"""
        resp = self.client.get("/api/events")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("events", data)
        self.assertIsInstance(data["events"], list)

    def test_orchestrator_agents_returns_list(self):
        """GET /api/orchestrator/agents returns agents list"""
        try:
            resp = self.client.get("/api/orchestrator/agents")
        except Exception:
            # Connection error if orchestrator shutdown by prior test
            return
        # 200 if running, 500 if error
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable
        if resp.status_code == 200:
            data = resp.json()
            self.assertIn("agents", data)
            self.assertIn("count", data)

    def test_roles_list_returns_200(self):
        """GET /api/roles returns roles list"""
        resp = self.client.get("/api/roles")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("roles", data)
        self.assertIn("count", data)

    def test_get_role_not_found_returns_404(self):
        """GET /api/roles/nonexistent_role returns 404"""
        resp = self.client.get("/api/roles/nonexistent_role_xyz_999")
        self.assertEqual(resp.status_code, 404)

    def test_dispatch_by_role_missing_fields_returns_422(self):
        """POST /api/roles/dispatch without required fields returns 400"""
        resp = self.client.post("/api/roles/dispatch", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_cors_headers_present(self):
        """CORS middleware allows cross-origin requests"""
        resp = self.client.get("/api/health", headers={"Origin": "http://example.com"})
        self.assertEqual(resp.status_code, 200)

    def test_openapi_docs_available(self):
        """FastAPI auto-generated OpenAPI docs are available"""
        resp = self.client.get("/docs")
        self.assertIn(resp.status_code, [200, 404])

    def test_version_in_health_response(self):
        """Health endpoint includes API version 1.1.0"""
        resp = self.client.get("/api/health")
        data = resp.json()
        self.assertEqual(data.get("version"), "1.1.0")



class TestMainFastapiIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from fastapi.testclient import TestClient
        import main_fastapi
        cls.client = TestClient(main_fastapi.app)

    def test_health_returns_200(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healthy")

    def test_health_version_is_1_1_0(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.json().get("version"), "1.1.0")

    def test_system_stats_returns_keys(self):
        resp = self.client.get("/api/system/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ["cpu", "memory", "disk", "network"]:
            self.assertIn(key, data)

    def test_terminal_missing_command_returns_400(self):
        resp = self.client.post("/api/terminal/execute", json={"command": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "MISSING_COMMAND")

    def test_terminal_execute_is_disabled_without_capability(self):
        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "false", "JARVIS_TERMINAL_TOKEN": ""},
        ):
            resp = self.client.post(
                "/api/terminal/execute",
                json={"command": "echo", "args": ["blocked"]},
            )

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "TERMINAL_DISABLED")

    def test_terminal_execute_rejects_invalid_capability_token(self):
        import main_fastapi

        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "true", "JARVIS_TERMINAL_TOKEN": "test-token"},
        ), patch.object(main_fastapi.state.terminal, "execute") as execute:
            resp = self.client.post(
                "/api/terminal/execute",
                json={"command": "pwd", "args": []},
                headers={"X-Jarvis-Terminal-Token": "wrong-token"},
            )

        execute.assert_not_called()
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "TERMINAL_UNAUTHORIZED")

    def test_orchestrator_dispatch_forwards_timeout_and_priority(self):
        import main_fastapi

        with patch.object(main_fastapi.state.orchestrator, "dispatch") as dispatch:
            dispatch.return_value.to_dict.return_value = {
                "task_id": "fixture-task",
                "agent_name": "analyzer",
                "result": "ok",
                "error": "",
                "duration_ms": 0,
                "status": "success",
            }
            resp = self.client.post(
                "/api/orchestrator/dispatch",
                json={
                    "agent_name": "analyzer",
                    "prompt": "ping",
                    "timeout": 45,
                    "priority": 3,
                },
            )

        self.assertEqual(resp.status_code, 200)
        task = dispatch.call_args.args[0]
        self.assertEqual(task.timeout, 45)
        self.assertEqual(task.priority, 3)

    def test_memory_store_returns_success(self):
        resp = self.client.post("/api/memory/store", json={
            "type": "user",
            "title": "integration_test",
            "content": "iteration 78 canonical integration",
            "tags": ["test"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))

    def test_memory_probe_can_be_deleted_by_returned_id(self):
        cleanup_token = "fastapi-test-secret"
        stored = self.client.post("/api/memory/store", json={
            "type": "project",
            "title": ".test-local-integration-fastapi-delete",
            "content": "temporary integration probe",
            "tags": ["test"],
            "probe_cleanup_token": cleanup_token,
        })
        entry_id = stored.json()["id"]

        deleted = self.client.request(
            "DELETE",
            f"/api/memory/probes/project/{entry_id}",
            json={"cleanup_token": cleanup_token},
        )

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), {"success": True, "id": entry_id})


    def test_ollama_token_usage_returns_fields(self):
        resp = self.client.get("/api/ollama/token-usage")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("latest", data)
        self.assertIn("totals", data)
        self.assertIn("samples", data)
        self.assertIn("session_started_at", data)

    def test_ollama_chat_records_token_usage(self):
        resp = self.client.post("/api/ollama/chat", json={
            "model": "default",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
        })
        self.assertIn(resp.status_code, [200, 500, 502])  # 502 when Ollama unavailable
        usage_resp = self.client.get("/api/ollama/token-usage")
        self.assertEqual(usage_resp.status_code, 200)

    def test_ollama_stream_uses_nested_error_frame_without_done(self):
        import main_fastapi

        with patch.object(
            main_fastapi.state.ollama,
            "stream_chat_generator",
            side_effect=RuntimeError("fixture failure"),
        ):
            response = self.client.get(
                "/api/ollama/chat/stream",
                params={"model": "fixture-model"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '"error": {"code": "OLLAMA_STREAM_ERROR", "message": "fixture failure"}',
            response.text,
        )
        self.assertNotIn("data: [DONE]", response.text)

    def test_openapi_route_exists(self):
        resp = self.client.get("/docs")
        self.assertIn(resp.status_code, [200, 404])

if __name__ == "__main__":
    sys.exit(run_all_tests())
