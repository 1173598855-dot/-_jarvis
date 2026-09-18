"""Extended tests for ollama_manager.py - Iteration 49"""
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.ollama_manager import (
    Command,
    OllamaManager,
    OllamaModel,
    OllamaStatus,
)


class TestOllamaModelExtended(unittest.TestCase):
    def test_defaults(self):
        m = OllamaModel(name="llama2", size="3.2GB",
                          digest="abc", modified_at="2024-01-01")
        self.assertIsNone(m.details)

    def test_with_details(self):
        m = OllamaModel(name="llama2", size="3.2GB",
                          digest="abc", modified_at="2024-01-01",
                          details={"quantization": "Q4_0"})
        self.assertEqual(m.details["quantization"], "Q4_0")

    def test_from_api_with_all_fields(self):
        data = {
            "name": "codellama",
            "size": "7B",
            "digest": "sha256:abc",
            "modified_at": "2024-01-01T00:00:00Z",
            "details": {"format": "GGUF"},
        }
        m = OllamaModel.from_api(data)
        self.assertEqual(m.name, "codellama")
        self.assertEqual(m.digest, "sha256:abc")


class TestOllamaStatusExtended(unittest.TestCase):
    def test_running_false_default(self):
        s = OllamaStatus(running=False)
        self.assertFalse(s.running)
        self.assertEqual(s.models, [])

    def test_running_true_with_models(self):
        model = OllamaModel(name="llama2", size="3.2GB",
                         digest="a", modified_at="2024-01-01")
        s = OllamaStatus(running=True, models=[model])
        self.assertTrue(s.running)
        self.assertEqual(len(s.models), 1)

    def test_post_init_sets_models_empty(self):
        s = OllamaStatus(running=True)
        self.assertEqual(s.models, [])


class TestOllamaManagerInitExtended(unittest.TestCase):
    def test_slash_stripped_from_url(self):
        mgr = OllamaManager(base_url="http://localhost:11434/")
        self.assertEqual(mgr.base_url, "http://localhost:11434")

    def test_no_trailing_slash_unchanged(self):
        mgr = OllamaManager(base_url="http://localhost:11434")
        self.assertEqual(mgr.base_url, "http://localhost:11434")

    def test_timeout_stored(self):
        mgr = OllamaManager(timeout=60)
        self.assertEqual(mgr.timeout, 60)


class TestOllamaManagerGetPost(unittest.TestCase):
    def test_get_success_returns_json(self):
        mgr = OllamaManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_resp.iter_content.return_value = [b'{"models": []}']
        mock_resp.raise_for_status = MagicMock()
        with patch.object(mgr._session, "get", return_value=mock_resp):
            result = mgr._get("/api/tags")
        self.assertIn("models", result)

    def test_get_returns_error_on_connection_error(self):
        mgr = OllamaManager()
        with patch.object(mgr._session, "get", side_effect=Exception("conn refused")):
            result = mgr._get("/api/tags")
        self.assertIn("error", result)

    def test_post_success(self):
        mgr = OllamaManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"model": "llama2",
                              "done": True}
        mock_resp.iter_content.return_value = [b'{"model": "llama2", "done": true}']
        mock_resp.raise_for_status = MagicMock()
        with patch.object(mgr._session, "post", return_value=mock_resp):
            result = mgr._post("api/generate", {"model": "llama2"})
        self.assertIn("model", result)


class TestOllamaManagerStatus(unittest.TestCase):
    def test_get_status_running(self):
        mgr = OllamaManager()
        version_data = {"version": "0.1.30"}
        model1 = {"name": "llama2", "size": "3.2GB"}
        model2 = {"name": "mistral", "size": "7B"}
        tags_data = {"models": [model1, model2]}
        ps_data = {"models": []}
        with patch.object(mgr, "_get", side_effect=[version_data, tags_data, ps_data]):
            status = mgr.get_status()
        self.assertTrue(status.running)
        self.assertEqual(len(status.models), 2)

    def test_get_status_not_running(self):
        mgr = OllamaManager()
        error_data = {"error": "not running"}
        with patch.object(mgr, "_get", return_value=error_data):
            status = mgr.get_status()
        self.assertFalse(status.running)


class TestOllamaManagerListModels(unittest.TestCase):
    def test_list_models_success(self):
        mgr = OllamaManager()
        model1 = {"name": "llama2", "size": "3.2GB"}
        model2 = {"name": "mistral", "size": "7B"}
        tags_data = {"models": [model1, model2]}
        with patch.object(mgr, "_get", return_value=tags_data):
            models = mgr.list_models()
        self.assertEqual(len(models), 2)

    def test_list_models_returns_empty_on_error(self):
        mgr = OllamaManager()
        error_data = {"error": "x"}
        with patch.object(mgr, "_get", return_value=error_data):
            models = mgr.list_models()
        self.assertEqual(models, [])


class TestOllamaManagerPullModel(unittest.TestCase):
    def test_pull_model_returns_success_dict(self):
        mgr = OllamaManager()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = [
            json.dumps({"status": "success"}).encode()
        ]
        mock_resp.iter_content.return_value = [b'{"status": "success"}\n']
        with patch.object(mgr._session, "post", return_value=mock_resp):
            result = mgr.pull_model("llama2")
        self.assertIn("success", result)
        self.assertIn("model", result)

    def test_pull_model_returns_error_on_exception(self):
        mgr = OllamaManager()
        with patch.object(mgr._session, "post", side_effect=Exception):
            result = mgr.pull_model("nonexistent")
        self.assertIn("error", result)


class TestOllamaManagerChat(unittest.TestCase):
    def test_chat_success_returns_message(self):
        mgr = OllamaManager()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "model": "llama2",
            "message": {"role": "assistant", "content": "Hello!"},
            "done": True,
        }
        mock_resp.iter_content.return_value = [
            b'{"model": "llama2", "message": {"role": "assistant", "content": "Hello!"}, "done": true}'
        ]
        mock_resp.raise_for_status = MagicMock()
        msgs = [{"role": "user", "content": "hi"}]
        with patch.object(mgr._session, "post", return_value=mock_resp):
            result = mgr.chat("llama2", msgs)
        self.assertIn("message", result)

    def test_chat_returns_error_on_exception(self):
        mgr = OllamaManager()
        msgs = [{"role": "user", "content": "hi"}]
        with patch.object(mgr._session, "post", side_effect=Exception):
            result = mgr.chat("llama2", msgs)
        self.assertIn("error", result)

    def test_chat_rejects_malformed_tool_calls(self):
        malformed_calls = [
            [{}],
            [{"function": {}}],
            [{"function": {"name": "", "arguments": {}}}],
            [{"function": {"name": "repository_metadata", "arguments": []}}],
            [{"function": {"name": "repository_metadata", "arguments": "{"}}],
            [{"id": "", "function": {"name": "repository_metadata", "arguments": {}}}],
        ]

        for tool_calls in malformed_calls:
            with self.subTest(tool_calls=tool_calls):
                mgr = OllamaManager()
                response = {
                    "model": "fixture",
                    "message": {"role": "assistant", "tool_calls": tool_calls},
                    "done": True,
                }
                with patch.object(mgr, "_post", return_value=response):
                    result = mgr.chat(
                        "fixture",
                        [{"role": "user", "content": "inspect"}],
                    )

                self.assertEqual(
                    result,
                    {"error": "Ollama chat response is invalid"},
                )


class TestOllamaManagerStreamChat(unittest.TestCase):
    def test_stream_chat_generator_yields_tuples(self):
        mgr = OllamaManager()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = [
            json.dumps({"message": {"content": "chunk1"}, "done": False}).encode(),
            json.dumps({"message": {"content": "chunk2"}, "done": True}).encode(),
        ]
        mock_resp.iter_content.return_value = [
            b'{"message": {"content": "chunk1"}, "done": false}\n'
            b'{"message": {"content": "chunk2"}, "done": true}\n'
        ]
        msgs = [{"role": "user", "content": "hi"}]
        with patch.object(mgr._session, "post", return_value=mock_resp):
            results = list(mgr.stream_chat_generator("llama2", msgs))
        self.assertTrue(len(results) >= 1)
        for item in results:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)

    def test_stream_chat_connection_error_yields_error(self):
        mgr = OllamaManager()
        msgs = [{"role": "user", "content": "hi"}]
        with patch.object(mgr._session, "post", side_effect=Exception):
            results = list(mgr.stream_chat_generator("llama2", msgs))
        self.assertTrue(len(results) >= 1)


class TestOllamaManagerGpuInfo(unittest.TestCase):
    def test_get_gpu_info_available(self):
        mgr = OllamaManager()
        ps_data = {
            "models": [{"name": "RTX4090"}],
        }
        with patch.object(mgr, "_get", return_value=ps_data):
            info = mgr.get_gpu_info()
        self.assertTrue(info["available"])

    def test_get_gpu_info_not_available(self):
        mgr = OllamaManager()
        error_data = {"error": "no gpu"}
        with patch.object(mgr, "_get", return_value=error_data):
            info = mgr.get_gpu_info()
        self.assertIn("error", info)


class TestOllamaManagerToDict(unittest.TestCase):
    def test_to_dict_running_with_models(self):
        model = OllamaModel(name="llama2", size="3.2GB",
                         digest="a", modified_at="2024-01-01")
        status = OllamaStatus(running=True, models=[model])
        mgr = OllamaManager()
        result = mgr.to_dict(status)
        self.assertTrue(result["running"])
        self.assertEqual(len(result["models"]), 1)

    def test_to_dict_not_running(self):
        status = OllamaStatus(running=False)
        mgr = OllamaManager()
        result = mgr.to_dict(status)
        self.assertFalse(result["running"])


class TestOllamaCommandEnum(unittest.TestCase):
    def test_command_values(self):
        self.assertEqual(Command.STATUS.value, "status")
        self.assertEqual(Command.PULL.value, "pull")
        self.assertEqual(Command.CHAT.value, "chat")
        self.assertEqual(Command.GPU.value, "gpu")


def run_all_tests():
    print("============================================================")
    print("J.A.R.V.I.S. ollama_manager extended tests - Iteration 49")
    print("============================================================")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestOllamaModelExtended, TestOllamaStatusExtended,
        TestOllamaManagerInitExtended, TestOllamaManagerGetPost,
        TestOllamaManagerStatus, TestOllamaManagerListModels,
        TestOllamaManagerPullModel, TestOllamaManagerChat,
        TestOllamaManagerStreamChat, TestOllamaManagerGpuInfo,
        TestOllamaManagerToDict, TestOllamaCommandEnum,
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
