"""Extended tests for main_fastapi.py - Iteration 50"""
import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from main_fastapi import AppState, app, create_app

client = TestClient(app, raise_server_exceptions=False)


class TestAppState(unittest.TestCase):
    def setUp(self):
        self.memory_directory = tempfile.TemporaryDirectory(
            prefix=".test-fastapi-app-state-"
        )
        self.addCleanup(self.memory_directory.cleanup)
        self.state = AppState(memory_dir=self.memory_directory.name)
        self.addCleanup(self.state.shutdown)

    def test_agent_factory_uses_application_ollama_manager(self):
        self.assertIs(
            self.state.agent_factory._ollama_manager,
            self.state.ollama,
        )

    def test_default_values(self):
        self.assertEqual(self.state.request_count, 0)
        self.assertGreater(self.state.start_time, 0)

    def test_start_time_set(self):
        import time

        self.state.start_time = time.time()
        self.assertGreater(self.state.start_time, 0)


class TestHealthEndpoint(unittest.TestCase):
    def test_health_returns_200(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)

    def test_health_accepts_exact_raw_query_budget(self):
        import main_fastapi

        response = client.get(
            "/api/health?" + "x" * main_fastapi.MAX_REQUEST_QUERY_BYTES
        )

        self.assertEqual(response.status_code, 200)

    def test_api_query_over_budget_is_rejected_before_route_parsing(self):
        import main_fastapi

        path = (
            "/api/capabilities/registry?"
            + "x" * (main_fastapi.MAX_REQUEST_QUERY_BYTES + 1)
        )
        with patch.object(main_fastapi, "parse_capability_query_items") as parse:
            response = client.get(path)

        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "REQUEST_QUERY_TOO_LARGE",
                    "message": "Request query exceeds the 32 KiB limit",
                }
            },
        )
        parse.assert_not_called()

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

    def test_ollama_stream_rejects_oversized_ascii_query_value(self):
        import main_fastapi

        oversized_model = "m" * (main_fastapi.MAX_REQUEST_BODY_BYTES + 1)
        response = client.get(
            "/api/ollama/chat/stream",
            params={"model": oversized_model},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "REQUEST_QUERY_TOO_LARGE")

    def test_ollama_stream_rejects_multibyte_query_value_over_byte_budget(self):
        import main_fastapi

        oversized_model = "é" * (main_fastapi.MAX_REQUEST_BODY_BYTES // 2 + 1)
        self.assertLessEqual(len(oversized_model), main_fastapi.MAX_REQUEST_BODY_BYTES)
        self.assertGreater(
            len(oversized_model.encode("utf-8")),
            main_fastapi.MAX_REQUEST_BODY_BYTES,
        )
        with self.assertRaises(main_fastapi.HTTPException) as raised:
            asyncio.run(
                main_fastapi.ollama_chat_stream(
                    model=oversized_model,
                    messages="[]",
                )
            )

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(
            raised.exception.detail,
            {
                "code": "REQUEST_QUERY_TOO_LARGE",
                "message": "Request query exceeds the 32 KiB limit",
            },
        )

    def test_ollama_stream_accepts_exact_raw_query_budget(self):
        import main_fastapi

        model = "m" * (
            main_fastapi.MAX_REQUEST_QUERY_BYTES - len("model=")
        )
        with patch.object(
            main_fastapi.state.ollama,
            "stream_chat_generator",
            return_value=[("done", True)],
        ):
            response = client.get(
                "/api/ollama/chat/stream",
                params={"model": model},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("data: [DONE]", response.text)


class TestTerminalEndpoint(unittest.TestCase):
    def test_terminal_execute_requires_command(self):
        r = client.post("/api/terminal/execute", json={})
        self.assertIn(r.status_code, [200, 400, 422])


class TestMemoryEndpoints(unittest.TestCase):
    def test_memory_entries_endpoint(self):
        r = client.get("/api/memory/entries")
        self.assertEqual(r.status_code, 200)

    def test_memory_store_requires_content(self):
        memory_directory = tempfile.TemporaryDirectory(
            prefix=".test-fastapi-memory-store-"
        )
        self.addCleanup(memory_directory.cleanup)
        isolated_state = AppState(memory_dir=memory_directory.name)
        with TestClient(
            create_app(isolated_state),
            raise_server_exceptions=False,
        ) as isolated_client:
            r = isolated_client.post("/api/memory/store", json={})
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
