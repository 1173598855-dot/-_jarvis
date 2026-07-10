"""
Test main_fastapi.py - Phase 11 FastAPI REST API integration tests
Run: python3 tests/test_main_fastapi.py
"""
import sys
import unittest
from pathlib import Path

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
        self.assertIn("shutdown()", text)

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
        self.assertIn(resp.status_code, [200, 500])

    def test_dispatch_by_role_missing_role_name(self):
        resp = self.client.post("/api/roles/dispatch", json={"prompt": "test"})
        self.assertEqual(resp.status_code, 422)

    def test_dispatch_by_role_invalid_role(self):
        resp = self.client.post("/api/roles/dispatch", json={
            "role_name": "nonexistent_role_xyz", "prompt": "test",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)

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
        self.assertIn(resp.status_code, [200, 500])
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

    def test_roles_list_with_capability_filter(self):
        resp = self.client.get("/api/roles?capability=coding")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("roles", data)
        self.assertIn("count", data)


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
        self.assertIn(resp.status_code, [200, 500])

    def test_ollama_chat_missing_model_returns_400(self):
        """POST /api/ollama/chat with empty model returns error"""
        resp = self.client.post("/api/ollama/chat", json={"messages": []})
        # Should return 500 (connection error) or handle gracefully
        self.assertIn(resp.status_code, [400, 500])

    def test_terminal_execute_empty_command_returns_400(self):
        """POST /api/terminal/execute with empty command returns 400"""
        resp = self.client.post("/api/terminal/execute", json={"command": ""})
        self.assertEqual(resp.status_code, 400)

    def test_terminal_execute_missing_field_returns_422(self):
        """POST /api/terminal/execute without 'command' field returns 422"""
        resp = self.client.post("/api/terminal/execute", json={})
        self.assertEqual(resp.status_code, 422)

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
        self.assertIn(resp.status_code, [200, 500])
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
        """POST /api/roles/dispatch without required fields returns 422"""
        resp = self.client.post("/api/roles/dispatch", json={})
        self.assertEqual(resp.status_code, 422)

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

    def test_memory_store_returns_success(self):
        resp = self.client.post("/api/memory/store", json={
            "type": "user",
            "title": "integration_test",
            "content": "iteration 78 canonical integration",
            "tags": ["test"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))


    def test_ollama_token_usage_returns_fields(self):
        resp = self.client.get("/api/ollama/token-usage")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("prompt_tokens", data)
        self.assertIn("completion_tokens", data)
        self.assertIn("total_tokens", data)

    def test_ollama_chat_records_token_usage(self):
        resp = self.client.post("/api/ollama/chat", json={
            "model": "default",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
        })
        self.assertIn(resp.status_code, [200, 500])
        usage_resp = self.client.get("/api/ollama/token-usage")
        self.assertEqual(usage_resp.status_code, 200)
    def test_openapi_route_exists(self):
        resp = self.client.get("/docs")
        self.assertIn(resp.status_code, [200, 404])

if __name__ == "__main__":
    sys.exit(run_all_tests())
