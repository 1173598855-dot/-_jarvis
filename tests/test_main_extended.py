"""Extended tests for main.py - Iteration 51"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "main_unit_test_ext",
    str(Path(__file__).parent.parent / "src" / "main.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
JARVISHandler = mod.JARVISHandler
AppState = mod.AppState
state = mod.state


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


class TestAppStateExtended(unittest.TestCase):
    def test_agent_factory_uses_application_ollama_manager(self):
        s = AppState()
        try:
            self.assertIs(s.agent_factory._ollama_manager, s.ollama)
        finally:
            s.terminal.close()

    def test_default_ollama_manager(self):
        s = AppState()
        self.assertIsNotNone(s.ollama)

    def test_default_terminal_executor(self):
        s = AppState()
        self.assertIsNotNone(s.terminal)

    def test_default_memory_store(self):
        s = AppState()
        self.assertIsNotNone(s.memory_store)

    def test_default_orchestrator(self):
        s = AppState()
        self.assertIsNotNone(s.orchestrator)

    def test_start_time_is_float(self):
        s = AppState()
        self.assertIsInstance(s.start_time, float)

    def test_increment_requests_positive(self):
        s = AppState()
        s.increment_requests()
        self.assertEqual(s.request_count, 1)

    def test_increment_requests_multiple(self):
        s = AppState()
        for _ in range(5):
            s.increment_requests()
        self.assertEqual(s.request_count, 5)

    def test_has_lock_attribute(self):
        s = AppState()
        self.assertTrue(hasattr(s, "_lock"))


class TestHandleSystemStats(unittest.TestCase):
    def _make_stats_handler(self):
        handler = _make_handler()
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        return handler

    def test_system_stats_sends_200(self):
        handler = self._make_stats_handler()
        with patch.dict("sys.modules", {"psutil": MagicMock()}, clear=False):
            import psutil
            psutil.cpu_percent = MagicMock(return_value=10.0)
            psutil.cpu_count = MagicMock(return_value=4)
            psutil.virtual_memory = MagicMock(return_value=
                type("M", (), {"total": 8e9, "used": 4e9, "free": 4e9, "percent": 50.0})())
            psutil.disk_usage = MagicMock(return_value=
                type("D", (), {"total": 500e9, "used": 250e9, "free": 250e9, "percent": 50.0})())
            psutil.net_if_addrs = MagicMock(return_value={})
            handler.handle_system_stats()
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("cpu", parsed)
        self.assertIn("memory", parsed)
        self.assertIn("disk", parsed)

    def test_system_stats_fallback_on_import_error(self):
        handler = self._make_stats_handler()
        with patch.dict("sys.modules", {"psutil": None}, clear=False):
            handler.handle_system_stats()
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["cpu"]["model"], "N/A")
        self.assertEqual(parsed["network"]["interfaces"], [])


class TestHandleOrchestratorDispatch(unittest.TestCase):
    def test_dispatch_success_returns_dict(self):
        handler = _make_handler(command="POST", path="/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": "0"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        body_data = json.dumps({"agent_name": "test_agent", "prompt": "do something"}).encode()
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = io.BytesIO(body_data)
        mock_result = MagicMock()
        mock_result.to_dict = MagicMock(return_value={"task_id": "t1", "status": "ok"})
        with patch.object(state.orchestrator, "dispatch", return_value=mock_result):
            handler.handle_orchestrator_dispatch()
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertEqual(parsed["task_id"], "t1")

    def test_dispatch_missing_agent_name_400(self):
        handler = _make_handler(command="POST", path="/api/orchestrator/dispatch")
        handler.headers = {"Content-Length": "0"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        body_data = json.dumps({"prompt": "no agent"}).encode()
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = io.BytesIO(body_data)
        handler.handle_orchestrator_dispatch()
        handler.send_response.assert_called_once_with(400)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("error", parsed)


class TestHandleOllamaChatStream(unittest.TestCase):
    def test_stream_returns_200(self):
        handler = _make_handler(path="/api/ollama/chat/stream")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        mock_gen = MagicMock(return_value=iter([("hello", True)]))
        with patch.object(state.ollama, "stream_chat_generator", mock_gen):
            handler.handle_ollama_chat_stream()
        handler.send_response.assert_called_once_with(200)
        ct_calls = [c for c in handler.send_header.call_args_list
                     if c[0][0] == "Content-Type"]
        self.assertEqual(len(ct_calls), 1)
        self.assertIn("text/event-stream", ct_calls[0][0][1])


class TestHandlePluginEndpointsExtended(unittest.TestCase):
    def test_plugin_enable_returns_success(self):
        handler = _make_handler(command="POST", path="/api/plugins/enable")
        handler.headers = {"Content-Length": "0"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        body_data = json.dumps({"plugin_id": "test_plugin"}).encode()
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = io.BytesIO(body_data)
        with patch.object(mod.global_plugin_manager, "enable", return_value=True):
            handler.handle_plugin_enable()
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertTrue(parsed["success"])

    def test_plugin_disable_returns_success(self):
        handler = _make_handler(command="POST", path="/api/plugins/disable")
        handler.headers = {"Content-Length": "0"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        body_data = json.dumps({"plugin_id": "test_plugin"}).encode()
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = io.BytesIO(body_data)
        with patch.object(mod.global_plugin_manager, "disable", return_value=True):
            handler.handle_plugin_disable()
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertTrue(parsed["success"])

    def test_plugin_disable_missing_id_400(self):
        handler = _make_handler(command="POST", path="/api/plugins/disable")
        handler.headers = {"Content-Length": "0"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        handler.handle_plugin_disable()
        handler.send_response.assert_called_once_with(400)


class TestHandleOrchestratorHistoryExtended(unittest.TestCase):
    def test_history_returns_results(self):
        handler = _make_handler(path="/api/orchestrator/history")
        handler.headers = {}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        mock_results = [MagicMock(), MagicMock()]
        mock_results[0].to_dict = MagicMock(return_value={"task_id": "t1"})
        mock_results[1].to_dict = MagicMock(return_value={"task_id": "t2"})
        with patch.object(state.orchestrator, "collect", return_value=mock_results):
            handler.handle_orchestrator_history()
        handler.send_response.assert_called_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertIn("results", parsed)
        self.assertEqual(parsed["count"], 2)

    def test_history_error_returns_500(self):
        handler = _make_handler(path="/api/orchestrator/history")
        handler.headers = {}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        with patch.object(state.orchestrator, "collect", side_effect=Exception("db error")):
            handler.handle_orchestrator_history()
        handler.send_response.assert_called_once_with(500)


class TestHandleMemoryStoreExtended(unittest.TestCase):
    def test_memory_store_with_tags(self):
        handler = _make_handler(command="POST", path="/api/memory/store")
        handler.headers = {"Content-Length": "0"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        body_data = json.dumps({
            "type": "project", "title": "ext_test",
            "content": "extended test content", "tags": ["a", "b"],
        }).encode()
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = io.BytesIO(body_data)
        handler.handle_memory_store()
        handler.send_response.assert_called_once_with(200)
        parsed = json.loads(handler.wfile.write.call_args[0][0])
        self.assertTrue(parsed.get("success"))

    def test_memory_store_invalid_type_defaults_user(self):
        handler = _make_handler(command="POST", path="/api/memory/store")
        handler.headers = {"Content-Length": "0"}
        for attr in ["send_response", "send_header", "end_headers", "wfile"]:
            setattr(handler, attr, MagicMock())
        body_data = json.dumps({"type": "invalid_type", "title": "t", "content": "c"}).encode()
        handler.headers["Content-Length"] = str(len(body_data))
        handler.rfile = io.BytesIO(body_data)
        handler.handle_memory_store()
        handler.send_response.assert_called_once_with(200)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. main.py extended tests - Iteration 51")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestAppStateExtended, TestHandleSystemStats,
        TestHandleOrchestratorDispatch, TestHandleOllamaChatStream,
        TestHandlePluginEndpointsExtended,
        TestHandleOrchestratorHistoryExtended,
        TestHandleMemoryStoreExtended,
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
