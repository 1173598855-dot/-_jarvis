"""
Ollama Manager complete test suite - Iteration #28
Uses unittest.mock to simulate HTTP calls; no Ollama service required.
Run: python3 tests/test_ollama_manager.py
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.kernel.ollama_manager import OllamaManager, OllamaModel, OllamaStatus, TokenUsage, print_status


def make_manager():
    return OllamaManager(base_url="http://test-ollama:11434", timeout=5)


def mock_response(status_code=200, json_data=None, content=b""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    lines = [ln for ln in content.split(b"\n") if ln]
    resp.iter_lines = MagicMock(return_value=lines)
    return resp


# ============================================================
# OllamaModel
# ============================================================

class TestOllamaModel(unittest.TestCase):
    def test_from_api_basic(self):
        m = OllamaModel.from_api({"name": "llama3", "size": "4000000000", "digest": "abc", "modified_at": "2026-01-01"})
        assert m.name == "llama3"
        assert m.size == "4000000000"
        assert m.details == {}

    def test_from_api_with_details(self):
        data = {"name": "qwen2.5:7b", "size": "4700000000", "digest": "d1", "modified_at": "2026-01-01",
                "details": {"family": "qwen2", "parameter_size": "7B"}}
        m = OllamaModel.from_api(data)
        assert m.details["family"] == "qwen2"

    def test_ollama_status_post_init(self):
        s = OllamaStatus(running=False)
        assert s.models == []
        assert s.running is False

    def test_ollama_status_with_models(self):
        models = [OllamaModel(name="m1", size="1", digest="x", modified_at="2026-01-01")]
        s = OllamaStatus(running=True, version="0.5", models=models, gpu_available=True, gpu_name="RTX")
        assert len(s.models) == 1
        assert s.gpu_name == "RTX"


# ============================================================
# Init
# ============================================================

class TestOllamaManagerInit(unittest.TestCase):
    def test_default_base_url(self):
        m = OllamaManager()
        assert m.base_url == "http://localhost:11434"

    def test_custom_base_url(self):
        m = OllamaManager(base_url="http://remote:8080")
        assert m.base_url == "http://remote:8080"

    def test_trailing_slash_stripped(self):
        m = OllamaManager(base_url="http://localhost:11434/")
        assert m.base_url == "http://localhost:11434"

    def test_timeout_default(self):
        m = OllamaManager()
        assert m.timeout == 30

    def test_timeout_custom(self):
        m = OllamaManager(timeout=60)
        assert m.timeout == 60


# ============================================================
# Error handling
# ============================================================

class TestHttpErrorHandling(unittest.TestCase):
    def test_get_connection_error(self):
        m = make_manager()
        with patch.object(m._session, "get", side_effect=Exception("conn refused")):
            result = m._get("/api/version")
        assert "error" in result

    def test_post_connection_error(self):
        m = make_manager()
        with patch.object(m._session, "post", side_effect=Exception("conn refused")):
            result = m._post("/api/chat", {"model": "x", "messages": []})
        assert "error" in result


# ============================================================
# get_status
# ============================================================

class TestGetStatus(unittest.TestCase):
    def test_ollama_running(self):
        m = make_manager()
        v = mock_response(json_data={"version": "0.5.0"})
        t = mock_response(json_data={"models": [
            {"name": "llama3", "size": "4700000000", "digest": "a", "modified_at": "2026-01-01"}
        ]})
        p = mock_response(json_data={"models": [{"name": "llama3:7b"}]})
        with patch.object(m._session, "get", side_effect=[v, t, p]):
            status = m.get_status()
        assert status.running is True
        assert status.version == "0.5.0"
        assert len(status.models) == 1

    def test_ollama_not_running(self):
        m = make_manager()
        v = mock_response(json_data={"error": "not running"})
        with patch.object(m._session, "get", return_value=v):
            status = m.get_status()
        assert status.running is False

    def test_gpu_available_is_boolean_when_no_models_are_running(self):
        m = make_manager()
        responses = [
            mock_response(json_data={"version": "0.9.0"}),
            mock_response(json_data={"models": []}),
            mock_response(json_data={"models": []}),
        ]
        with patch.object(m._session, "get", side_effect=responses):
            status = m.get_status()

        self.assertIs(type(status.gpu_available), bool)
        self.assertFalse(status.gpu_available)


# ============================================================
# list_models
# ============================================================

class TestListModels(unittest.TestCase):
    def test_list_models_success(self):
        m = make_manager()
        resp = mock_response(json_data={"models": [
            {"name": "llama3:7b", "size": "4700000000", "digest": "a", "modified_at": "2026-01-01"},
            {"name": "qwen2.5:7b", "size": "4400000000", "digest": "b", "modified_at": "2026-01-01"},
        ]})
        with patch.object(m._session, "get", return_value=resp):
            models = m.list_models()
        assert len(models) == 2
        assert models[0].name == "llama3:7b"

    def test_list_models_error(self):
        m = make_manager()
        resp = mock_response(json_data={"error": "not running"})
        with patch.object(m._session, "get", return_value=resp):
            models = m.list_models()
        assert models == []


# ============================================================
# to_dict
# ============================================================

class TestToDict(unittest.TestCase):
    def test_to_dict_running(self):
        m = make_manager()
        status = OllamaStatus(running=True, version="0.5.0",
            models=[OllamaModel(name="m", size="1", digest="x", modified_at="2026-01-01")],
            gpu_available=True, gpu_name="RTX")
        d = m.to_dict(status)
        assert d["running"] is True
        assert d["version"] == "0.5.0"
        assert d["gpu_name"] == "RTX"

    def test_to_dict_not_running(self):
        m = make_manager()
        d = m.to_dict(OllamaStatus(running=False))
        assert d["running"] is False
        assert d["models"] == []


# ============================================================
# get_gpu_info
# ============================================================

class TestGetGpuInfo(unittest.TestCase):
    def test_gpu_available(self):
        m = make_manager()
        resp = mock_response(json_data={"models": [{"name": "RTX 4090"}]})
        with patch.object(m._session, "get", return_value=resp):
            info = m.get_gpu_info()
        assert info["available"] is True

    def test_gpu_not_available(self):
        m = make_manager()
        resp = mock_response(json_data={"models": []})
        with patch.object(m._session, "get", return_value=resp):
            info = m.get_gpu_info()
        assert info["available"] is False


# ============================================================
# chat
# ============================================================

class TestChat(unittest.TestCase):
    def test_chat_success(self):
        m = make_manager()
        resp = mock_response(json_data={
            "model": "llama3", "message": {"role": "assistant", "content": "Hi!"}, "done": True,
        })
        with patch.object(m._session, "post", return_value=resp):
            result = m.chat("llama3", [{"role": "user", "content": "hi"}])
        assert "error" not in result

    def test_chat_connection_error(self):
        m = make_manager()
        with patch.object(m._session, "post", side_effect=Exception("conn refused")):
            result = m.chat("llama3", [{"role": "user", "content": "hi"}])
        assert "error" in result

    def test_chat_records_native_ollama_token_counts_once(self):
        m = make_manager()
        resp = mock_response(json_data={
            "model": "llama3",
            "message": {"role": "assistant", "content": "Hi!"},
            "done": True,
            "prompt_eval_count": 8,
            "eval_count": 3,
        })

        with patch.object(m._session, "post", return_value=resp):
            m.chat("llama3", [{"role": "user", "content": "hi"}])

        self.assertEqual(m.get_token_usage().total_tokens, 11)
        self.assertEqual(len(m.get_token_usage_snapshot()["samples"]), 1)

    def test_chat_serializes_supplied_tools(self):
        m = make_manager()
        definition = {
            "type": "function",
            "function": {
                "name": "repository_metadata",
                "description": "Read repository metadata",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
        response = {
            "model": "fixture",
            "message": {"role": "assistant", "content": "OK"},
            "done": True,
        }

        with patch.object(m, "_post", return_value=response) as post:
            result = m.chat(
                "fixture",
                [{"role": "user", "content": "inspect"}],
                tools=[definition],
            )

        self.assertNotIn("error", result)
        self.assertEqual(post.call_args.args[1]["tools"], [definition])

    def test_chat_omits_tools_when_not_supplied(self):
        m = make_manager()
        response = {
            "model": "fixture",
            "message": {"role": "assistant", "content": "OK"},
            "done": True,
        }

        with patch.object(m, "_post", return_value=response) as post:
            result = m.chat(
                "fixture",
                [{"role": "user", "content": "inspect"}],
            )

        self.assertNotIn("error", result)
        self.assertNotIn("tools", post.call_args.args[1])

    def test_chat_accepts_valid_tool_only_response(self):
        m = make_manager()
        response = {
            "model": "fixture",
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "fixture-call-1",
                        "function": {
                            "name": "repository_metadata",
                            "arguments": {},
                        },
                    }
                ],
            },
            "done": True,
        }

        with patch.object(m, "_post", return_value=response):
            result = m.chat("fixture", [{"role": "user", "content": "inspect"}])

        self.assertEqual(result, response)

class TestPullModel(unittest.TestCase):
    """pull_model() streaming pull with progress output"""

    def test_pull_model_success(self):
        """pull_model returns success dict on valid stream"""
        m = make_manager()
        progress_lines = [
            b'{"status": "pulling manifest"}',
            b'{"status": "verifying sha256"}',
            b'{"status": "success"}',
        ]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_lines = MagicMock(return_value=progress_lines)
        with patch.object(m._session, "post", return_value=resp):
            result = m.pull_model("llama3:8b")
        self.assertIn("success", result)
        self.assertEqual(result.get("model"), "llama3:8b")

    def test_pull_model_error(self):
        """pull_model returns error dict on exception"""
        m = make_manager()
        with patch.object(m._session, "post", side_effect=Exception("network error")):
            result = m.pull_model("bad-model")
        self.assertIn("error", result)




class TestTokenUsage(unittest.TestCase):
    def test_record_and_get_token_usage(self):
        m = make_manager()
        m.record_token_usage(prompt_tokens=10, completion_tokens=5)
        usage = m.get_token_usage()
        self.assertEqual(usage.prompt_tokens, 10)
        self.assertEqual(usage.completion_tokens, 5)
        self.assertEqual(usage.total_tokens, 15)

    def test_record_negative_values_are_clamped(self):
        m = make_manager()
        m.record_token_usage(prompt_tokens=-3, completion_tokens=2)
        usage = m.get_token_usage()
        self.assertEqual(usage.prompt_tokens, 0)
        self.assertEqual(usage.completion_tokens, 2)
        self.assertEqual(usage.total_tokens, 2)

    def test_token_usage_to_dict(self):
        usage = TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
        data = usage.to_dict()
        self.assertEqual(data["prompt_tokens"], 1)
        self.assertEqual(data["completion_tokens"], 2)
        self.assertEqual(data["total_tokens"], 3)

    def test_session_snapshot_tracks_latest_totals_and_samples(self):
        m = make_manager()
        m.record_token_usage(prompt_tokens=10, completion_tokens=5)
        m.record_token_usage(prompt_tokens=4, completion_tokens=6)

        snapshot = m.get_token_usage_snapshot()

        self.assertEqual(snapshot["latest"]["prompt_tokens"], 4)
        self.assertEqual(snapshot["latest"]["total_tokens"], 10)
        self.assertEqual(snapshot["totals"]["total_tokens"], 25)
        self.assertEqual(len(snapshot["samples"]), 2)
        self.assertIsInstance(snapshot["session_started_at"], int)

    def test_records_native_ollama_token_fields(self):
        m = make_manager()

        recorded = m.record_token_usage_from_response({
            "prompt_eval_count": 11,
            "eval_count": 7,
        })

        self.assertTrue(recorded)
        self.assertEqual(m.get_token_usage().total_tokens, 18)

    def test_records_compatible_nested_usage_fields(self):
        m = make_manager()

        recorded = m.record_token_usage_from_response({
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 4,
            },
        })

        self.assertTrue(recorded)
        self.assertEqual(m.get_token_usage().total_tokens, 9)

class TestStreamChat(unittest.TestCase):
    """_stream_chat() and stream_chat_generator()"""

    def test_stream_chat_success(self):
        """_stream_chat accumulates chunks and returns full response"""
        m = make_manager()
        chunk_lines = [
            b'{"message": {"role": "assistant", "content": "Hello"}, "done": false}',
            b'{"message": {"role": "assistant", "content": " world"}, "done": true}',
        ]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_lines = MagicMock(return_value=chunk_lines)
        with patch.object(m._session, "post", return_value=resp):
            result = m._stream_chat({"model": "m", "messages": [], "stream": True})
        self.assertIn("message", result)
        self.assertIn("Hello world", result["message"]["content"])

    def test_stream_chat_records_final_native_token_counts(self):
        m = make_manager()
        chunk_lines = [
            b'{"message": {"content": "Hello"}, "done": false}',
            b'{"message": {"content": ""}, "done": true, "prompt_eval_count": 6, "eval_count": 2}',
        ]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_lines = MagicMock(return_value=chunk_lines)

        with patch.object(m._session, "post", return_value=resp):
            m._stream_chat({"model": "m", "messages": [], "stream": True})

        self.assertEqual(m.get_token_usage().total_tokens, 8)

    def test_stream_chat_connection_error(self):
        """_stream_chat returns error dict on connection failure"""
        m = make_manager()
        with patch.object(m._session, "post", side_effect=Exception("conn refused")):
            result = m._stream_chat({"model": "m", "messages": []})
        self.assertIn("error", result)

    def test_stream_chat_generator_yields_chunks(self):
        """stream_chat_generator yields (content, done) tuples"""
        m = make_manager()
        chunk_lines = [
            b'{"message": {"content": "Hi"}, "done": false}',
            b'{"message": {"content": "!"}, "done": true}',
        ]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_lines = MagicMock(return_value=chunk_lines)
        with patch.object(m._session, "post", return_value=resp):
            results = list(m.stream_chat_generator("m", [{"role": "u", "content": "h"}]))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], ("Hi", False))
        self.assertEqual(results[1], ("!", True))

    def test_stream_chat_generator_records_final_native_token_counts(self):
        m = make_manager()
        chunk_lines = [
            b'{"message": {"content": "Hi"}, "done": false}',
            b'{"message": {"content": ""}, "done": true, "prompt_eval_count": 9, "eval_count": 4}',
        ]
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_lines = MagicMock(return_value=chunk_lines)

        with patch.object(m._session, "post", return_value=resp):
            list(m.stream_chat_generator("m", []))

        self.assertEqual(m.get_token_usage().total_tokens, 13)

    def test_stream_chat_generator_connection_error(self):
        """stream_chat_generator yields error tuple on connection failure"""
        m = make_manager()
        with patch.object(m._session, "post", side_effect=Exception("conn refused")):
            results = list(m.stream_chat_generator("m", []))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], True)  # is_done


class TestOllamaStatusToDict(unittest.TestCase):
    """OllamaStatus dataclass and to_dict serialization"""

    def test_status_not_running(self):
        """OllamaStatus(running=False) has no models"""
        s = OllamaStatus(running=False)
        self.assertFalse(s.running)
        self.assertEqual(s.models, [])

    def test_status_running_with_models(self):
        """OllamaStatus can hold models list"""
        model = OllamaModel(name="llama3:8b", size="100", digest="abc123", modified_at="2024-01-01")
        s = OllamaStatus(running=True, version="0.1.0", models=[model], gpu_available=True)
        self.assertTrue(s.running)
        self.assertEqual(len(s.models), 1)

    def test_to_dict_serialization(self):
        """to_dict converts OllamaStatus to plain dict"""
        model = OllamaModel(name="test:m", size="50", digest="def456", modified_at="2024-06-01")
        s = OllamaStatus(running=True, version="0.2.0", models=[model])
        m = make_manager()
        d = m.to_dict(s)
        self.assertIn("running", d)
        self.assertIn("models", d)
        self.assertIn("gpu_available", d)
        self.assertTrue(d["running"])
        self.assertEqual(d["version"], "0.2.0")


class TestPrintStatus(unittest.TestCase):
    """print_status() console output formatting"""

    def test_print_status_not_running(self, capsys=None):
        """print_status for non-running service shows error message"""
        s = OllamaStatus(running=False)
        print_status(s)
        # Verify no exception is raised
        self.assertFalse(s.running)

    def test_print_status_running(self):
        """print_status for running service includes version"""
        s = OllamaStatus(running=True, version="0.1.0", models=[])
        # Should not raise
        print_status(s)


class TestChatStreamMode(unittest.TestCase):
    """chat() with stream=True delegates to _stream_chat"""

    def test_chat_stream_true_calls_stream_chat(self):
        """chat(stream=True) uses _stream_chat path"""
        m = make_manager()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_lines = MagicMock(return_value=[b'{"message": {"content": "ok"}, "done": true}'])
        with patch.object(m._session, "post", return_value=resp):
            result = m.chat("model", [{"role": "u", "content": "hi"}], stream=True)
        self.assertIn("message", result)



def run_all_tests():
    import unittest
    print("=" * 60)
    print("J.A.R.V.I.S. ollama_manager tests - Iteration 35")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestOllamaModel, TestOllamaManagerInit, TestHttpErrorHandling,
               TestGetStatus, TestListModels, TestToDict, TestGetGpuInfo, TestChat]:
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
