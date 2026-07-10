"""Extended tests for context_compressor.py - LLMCompressor + AdaptiveContextCompressor - Iter #60"""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.context_compressor import (
    AdaptiveContextCompressor,
    LLMCompressor,
    MemoryEntry,
    MemoryType,
    SemanticCompressor,
)


def _make_entry(title="t", content="hello world", importance=0.5, token_count=None):
    e = MemoryEntry.create(MemoryType.USER, title, content, importance=importance)
    if token_count is not None:
        e.token_count = token_count
    return e


class TestLLMCompressorInit(unittest.TestCase):
    def test_default_params(self):
        c = LLMCompressor()
        self.assertIsNone(c.ollama_manager)
        self.assertEqual(c.model, "llama3.2")
        self.assertEqual(c.token_budget, 4000)

    def test_custom_params(self):
        mock_mgr = MagicMock()
        c = LLMCompressor(ollama_manager=mock_mgr, model="mistral", token_budget=2000)
        self.assertEqual(c.ollama_manager, mock_mgr)
        self.assertEqual(c.model, "mistral")
        self.assertEqual(c.token_budget, 2000)

    def test_fallback_created(self):
        c = LLMCompressor(token_budget=3000)
        self.assertIsInstance(c._fallback, SemanticCompressor)
        self.assertEqual(c._fallback.token_budget, 3000)


class TestLLMCompressorCompressNoOllama(unittest.TestCase):
    def test_empty_entries_returns_empty(self):
        c = LLMCompressor()
        result, stats = c.compress_entries([])
        self.assertEqual(result, [])
        self.assertEqual(stats["total"], 0)
        self.assertFalse(stats.get("llm_available", True))

    def test_no_ollama_uses_fallback(self):
        c = LLMCompressor()
        entries = [_make_entry("e1", "content " * 50, importance=0.8)]
        result, stats = c.compress_entries(entries)
        self.assertFalse(stats.get("llm_available", True))
        self.assertEqual(stats["total"], 1)

    def test_with_ollama_manager_calls_chat(self):
        mock_mgr = MagicMock()
        mock_mgr.chat.return_value = {"message": {"content": "summary"}}
        c = LLMCompressor(ollama_manager=mock_mgr, token_budget=100)
        e = _make_entry("e1", "content", importance=0.9, token_count=500)
        result, stats = c.compress_entries([e])
        self.assertTrue(stats.get("llm_available", False))
        mock_mgr.chat.assert_called_once()
        self.assertEqual(stats["llm_summarized"], 1)

    def test_ollama_exception_falls_back(self):
        mock_mgr = MagicMock()
        mock_mgr.chat.side_effect = Exception("connection refused")
        c = LLMCompressor(ollama_manager=mock_mgr, token_budget=100)
        e = _make_entry("e1", "content", importance=0.9, token_count=500)
        result, stats = c.compress_entries([e])
        self.assertIsInstance(result, list)


class TestLLMCompressorCompressBehavior(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_mgr.chat.return_value = {"message": {"content": "LLM summary"}}
        self.c = LLMCompressor(ollama_manager=self.mock_mgr, token_budget=100)

    def test_high_importance_triggers_llm(self):
        e = _make_entry("e1", "x", importance=0.9, token_count=500)
        result, stats = self.c.compress_entries([e])
        self.assertEqual(stats["llm_summarized"], 1)
        self.assertTrue(result[0].title.endswith("[llm-summary]"))

    def test_low_importance_pruned(self):
        e = _make_entry("e1", "x", importance=0.1, token_count=500)
        result, stats = self.c.compress_entries([e])
        self.assertEqual(len(result), 0)

    def test_medium_importance_heuristic(self):
        e = _make_entry("e1", "decided: use plan A.", importance=0.5, token_count=500)
        result, stats = self.c.compress_entries([e])
        self.assertGreaterEqual(stats["heuristic_summarized"], 1)

    def test_within_budget_entry_kept(self):
        e = _make_entry("e1", "short", importance=0.9, token_count=50)
        result, stats = self.c.compress_entries([e])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "e1")

    def test_llm_empty_response_falls_to_heuristic(self):
        self.mock_mgr.chat.return_value = {"message": {"content": ""}}
        e = _make_entry("e1", "decided: test.", importance=0.9, token_count=500)
        result, stats = self.c.compress_entries([e])
        self.assertEqual(stats["llm_summarized"], 0)


class TestLLMCompressorHistory(unittest.TestCase):
    def test_history_records_actions(self):
        c = LLMCompressor()
        entries = [_make_entry("e1", "c" * 100, importance=0.9, token_count=500)]
        c.compress_entries(entries)
        self.assertGreater(len(c.compression_history), 0)
        record = c.compression_history[0]
        self.assertIn("action", record)
        self.assertIn("entry_id", record)
        self.assertIn("timestamp", record)

    def test_clear_history(self):
        c = LLMCompressor()
        entries = [_make_entry("e1", "c" * 100, importance=0.9, token_count=500)]
        c.compress_entries(entries)
        c.clear_history()
        self.assertEqual(len(c.compression_history), 0)

    def test_history_property_returns_copy(self):
        c = LLMCompressor()
        h1 = c.compression_history
        h1.append({"fake": True})
        self.assertEqual(len(c.compression_history), 0)

    def test_fallback_records_fallback_action(self):
        c = LLMCompressor()
        entries = [_make_entry("e1", "x", importance=0.9)]
        c.compress_entries(entries)
        actions = [r["action"] for r in c.compression_history]
        self.assertIn("fallback", actions)


class TestAdaptiveContextCompressorInit(unittest.TestCase):
    def test_default_params(self):
        c = AdaptiveContextCompressor()
        self.assertEqual(c.max_tokens, 4000)
        self.assertIsNone(c.llm_compressor.ollama_manager)

    def test_custom_params(self):
        mock_mgr = MagicMock()
        c = AdaptiveContextCompressor(max_tokens=2000, ollama_manager=mock_mgr, llm_model="phi3")
        self.assertEqual(c.max_tokens, 2000)
        self.assertEqual(c.llm_compressor.model, "phi3")


class TestAdaptiveContextCompressorRatios(unittest.TestCase):
    def test_empty_conversation(self):
        c = AdaptiveContextCompressor(max_tokens=100)
        result = c.compress([])
        self.assertEqual(result, "")

    def test_low_ratio_no_compression(self):
        c = AdaptiveContextCompressor(max_tokens=10000)
        conv = [{"role": "user", "content": "hi"}] * 5
        result = c.compress(conv)
        self.assertIn("user:", result)
        self.assertNotIn("[SUMMARY]", result)

    def test_medium_ratio_truncation(self):
        # truncation path: ratio in [0.3, 0.7)
        # budget=200, ratio=0.5, total=400: 5*80=400
        c = AdaptiveContextCompressor(max_tokens=200)
        conv = [{"role": "user", "content": "x" * 80}] * 5
        result = c.compress(conv)
        # Truncation produces role-prefixed lines, no [SUMMARY] marker
        self.assertIn("user:", result)
        self.assertNotIn("[SUMMARY]", result)

    def test_high_ratio_summarization(self):
        c = AdaptiveContextCompressor(max_tokens=100)
        conv = [{"role": "user", "content": "msg " + str(i)} for i in range(20)]
        result = c.compress(conv)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_super_budget_semantic_compress(self):
        c = AdaptiveContextCompressor(max_tokens=50)
        conv = [{"role": "user", "content": "x" * 200}] * 20
        result = c.compress(conv)
        self.assertIsInstance(result, str)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. context_compressor LLM extended tests - Iter #60")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestLLMCompressorInit,
        TestLLMCompressorCompressNoOllama,
        TestLLMCompressorCompressBehavior,
        TestLLMCompressorHistory,
        TestAdaptiveContextCompressorInit,
        TestAdaptiveContextCompressorRatios,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\nResults: {total} tests, {passed} passed")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_all_tests())
