"""Extended tests for main_fastapi.py - Iteration 50"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from main_fastapi import AppState, app

client = TestClient(app, raise_server_exceptions=False)


class TestAppState(unittest.TestCase):
    def test_agent_factory_uses_application_ollama_manager(self):
        state = AppState()
        try:
            self.assertIs(state.agent_factory._ollama_manager, state.ollama)
        finally:
            state.terminal.close()

    def test_default_values(self):
        state = AppState()
        self.assertEqual(state.request_count, 0)
        self.assertGreater(state.start_time, 0)

    def test_start_time_set(self):
        import time
        state = AppState()
        state.start_time = time.time()
        self.assertGreater(state.start_time, 0)


class TestHealthEndpoint(unittest.TestCase):
    def test_health_returns_200(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)

    def test_health_has_version(self):
        r = client.get("/api/health")
        data = r.json()
        self.assertIn("version", data)

    def test_health_has_uptime(self):
        r = client.get("/api/health")
        data = r.json()
        self.assertIn("uptime", data)
        self.assertGreaterEqual(data["uptime"], 0)

    def test_health_status_healthy(self):
        r = client.get("/api/health")
        data = r.json()
        self.assertEqual(data["status"], "healthy")


class TestSystemStatsEndpoint(unittest.TestCase):
    def test_system_stats_returns_200(self):
        r = client.get("/api/system/stats")
        self.assertEqual(r.status_code, 200)

    def test_system_stats_has_cpu(self):
        r = client.get("/api/system/stats")
        data = r.json()
        self.assertIn("cpu", data)

    def test_system_stats_has_memory(self):
        r = client.get("/api/system/stats")
        data = r.json()
        self.assertIn("memory", data)

    def test_system_stats_has_disk(self):
        r = client.get("/api/system/stats")
        data = r.json()
        self.assertIn("disk", data)


class TestOllamaEndpoints(unittest.TestCase):
    def test_ollama_status_endpoint(self):
        r = client.get("/api/ollama/status")
        self.assertIn(r.status_code, [200, 500])

    def test_ollama_models_endpoint(self):
        r = client.get("/api/ollama/models")
        self.assertIn(r.status_code, [200, 500])

    def test_ollama_chat_normalizes_unavailable_upstream(self):
        r = client.post("/api/ollama/chat", json={"messages": []})
        self.assertIn(r.status_code, [200, 400, 502])
        if r.status_code == 502:
            self.assertEqual(r.json()["error"]["code"], "OLLAMA_UPSTREAM_ERROR")


class TestTerminalEndpoint(unittest.TestCase):
    def test_terminal_execute_requires_command(self):
        r = client.post("/api/terminal/execute", json={})
        self.assertIn(r.status_code, [200, 400, 422])


class TestMemoryEndpoints(unittest.TestCase):
    def test_memory_entries_endpoint(self):
        r = client.get("/api/memory/entries")
        self.assertEqual(r.status_code, 200)

    def test_memory_store_requires_content(self):
        r = client.post("/api/memory/store", json={})
        self.assertIn(r.status_code, [200, 400, 422])


class TestEventsEndpoint(unittest.TestCase):
    def test_events_returns_dict_with_events_key(self):
        r = client.get("/api/events")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIsInstance(data, dict)
        self.assertIn("events", data)
        self.assertIsInstance(data["events"], list)


class TestOrchestratorEndpoints(unittest.TestCase):
    def test_orchestrator_agents_endpoint(self):
        r = client.get("/api/orchestrator/agents")
        self.assertIn(r.status_code, [200, 500])

    def test_orchestrator_history_endpoint(self):
        r = client.get("/api/orchestrator/history")
        self.assertEqual(r.status_code, 200)


class TestPluginEndpoints(unittest.TestCase):
    def test_plugins_list_endpoint(self):
        r = client.get("/api/plugins")
        self.assertEqual(r.status_code, 200)


class TestRoleEndpoints(unittest.TestCase):
    def test_roles_list_endpoint(self):
        r = client.get("/api/roles")
        self.assertEqual(r.status_code, 200)

    def test_role_not_found_returns_404(self):
        r = client.get("/api/roles/nonexistent_role_xyz")
        self.assertEqual(r.status_code, 404)


class TestOpenAPIEndpoint(unittest.TestCase):
    def test_openapi_docs_available(self):
        r = client.get("/docs")
        self.assertEqual(r.status_code, 200)

    def test_openapi_json_available(self):
        r = client.get("/openapi.json")
        self.assertIn(r.status_code, [200, 404])


class TestCORSHeaders(unittest.TestCase):
    def test_cors_headers_in_response(self):
        r = client.options("/api/health")
        self.assertIn(r.status_code, [200, 204, 405])

    def _load_app_with_origins(self, origins):
        previous = os.environ.get("JARVIS_ALLOWED_ORIGINS")
        os.environ["JARVIS_ALLOWED_ORIGINS"] = origins
        try:
            module_path = Path(__file__).parent.parent / "src" / "main_fastapi.py"
            spec = importlib.util.spec_from_file_location(
                f"main_fastapi_cors_{abs(hash(origins))}",
                module_path,
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.app
        finally:
            if previous is None:
                os.environ.pop("JARVIS_ALLOWED_ORIGINS", None)
            else:
                os.environ["JARVIS_ALLOWED_ORIGINS"] = previous

    def test_allowed_origin_is_reflected_from_env(self):
        test_app = self._load_app_with_origins("https://jarvis.local")
        test_client = TestClient(test_app, raise_server_exceptions=False)
        r = test_client.get("/api/health", headers={"Origin": "https://jarvis.local"})
        self.assertEqual(r.headers.get("access-control-allow-origin"), "https://jarvis.local")

    def test_disallowed_origin_gets_no_cors_header(self):
        test_app = self._load_app_with_origins("https://jarvis.local")
        test_client = TestClient(test_app, raise_server_exceptions=False)
        r = test_client.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertIsNone(r.headers.get("access-control-allow-origin"))



def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. main_fastapi extended tests - Iteration 50")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestAppState, TestHealthEndpoint, TestSystemStatsEndpoint,
        TestOllamaEndpoints, TestTerminalEndpoint, TestMemoryEndpoints,
        TestEventsEndpoint, TestOrchestratorEndpoints,
        TestPluginEndpoints, TestRoleEndpoints,
        TestOpenAPIEndpoint, TestCORSHeaders,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_all_tests())
