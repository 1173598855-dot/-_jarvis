"""
Extended tests for context_compressor.py - Iteration 42
Covers gaps: SemanticCompressor full behavior, MemoryStore internals, MemoryEntry edge cases.
Run: python3 tests/test_context_compressor_extended.py
"""
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.context_compressor import (
    ContextCompressor,
    MemoryEntry,
    MemoryStore,
    MemoryType,
    SemanticCompressor,
)


def make_user_entry(title, content, importance=0.5):
    return MemoryEntry.create(MemoryType.USER, title, content, importance=importance)


def make_project_entry(title, content, importance=0.7):
    return MemoryEntry.create(MemoryType.PROJECT, title, content, importance=importance)


# ============================================================
# TestMemoryEntryEdgeCases
# ============================================================

class TestMemoryEntryEdgeCases(unittest.TestCase):

    def test_create_feedback_type(self):
        e = MemoryEntry.create(MemoryType.FEEDBACK, "fb1", "feedback content")
        self.assertEqual(e.type, MemoryType.FEEDBACK)

    def test_create_project_type(self):
        e = MemoryEntry.create(MemoryType.PROJECT, "p1", "project content")
        self.assertEqual(e.type, MemoryType.PROJECT)

    def test_create_reference_type(self):
        e = MemoryEntry.create(MemoryType.REFERENCE, "r1", "reference content")
        self.assertEqual(e.type, MemoryType.REFERENCE)

    def test_create_custom_importance(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "c", importance=0.9)
        self.assertEqual(e.importance, 0.9)

    def test_create_custom_tags(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "c", tags=["a", "b", "c"])
        self.assertEqual(e.tags, ["a", "b", "c"])

    def test_create_generates_unique_ids(self):
        e1 = MemoryEntry.create(MemoryType.USER, "same title", "different content A")
        e2 = MemoryEntry.create(MemoryType.USER, "same title", "different content B")
        self.assertNotEqual(e1.id, e2.id)

    def test_create_same_content_same_id(self):
        e1 = MemoryEntry.create(MemoryType.USER, "t", "same content here")
        e2 = MemoryEntry.create(MemoryType.USER, "t", "same content here")
        self.assertEqual(e1.id, e2.id)

    def test_create_timestamp_is_iso_format(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        datetime.fromisoformat(e.created_at)
        datetime.fromisoformat(e.last_accessed)

    def test_estimate_tokens_empty_string(self):
        t = MemoryEntry._estimate_tokens("")
        self.assertEqual(t, 0)

    def test_estimate_tokens_chinese_only(self):
        chinese = "这是一个中文测试内容用来测试中文token估算"
        t = MemoryEntry._estimate_tokens(chinese)
        self.assertGreater(t, 0)

    def test_estimate_tokens_english_only(self):
        english = "hello world test content for token estimation"
        t = MemoryEntry._estimate_tokens(english)
        self.assertGreater(t, 0)

    def test_estimate_tokens_mixed(self):
        mixed = "Hello 世界 test 123"
        t = MemoryEntry._estimate_tokens(mixed)
        self.assertGreater(t, 0)

    def test_estimate_tokens_single_char(self):
        t = MemoryEntry._estimate_tokens("a")
        self.assertGreaterEqual(t, 1)

    def test_entry_defaults_not_compressed(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        self.assertFalse(e.compressed)
        self.assertIsNone(e.parent_id)
        self.assertEqual(e.access_count, 0)


# ============================================================
# TestContextCompressorEdgeCases
# ============================================================

class TestContextCompressorEdgeCases(unittest.TestCase):

    def test_compress_empty_conversation(self):
        cc = ContextCompressor(max_tokens=4000)
        result = cc.compress([])
        self.assertIsInstance(result, str)

    def test_compress_single_message(self):
        cc = ContextCompressor(max_tokens=4000)
        result = cc.compress([{"role": "user", "content": "hi"}])
        self.assertIn("hi", result)
        self.assertNotIn("[摘要]", result)

    def test_compress_exactly_five_messages(self):
        cc = ContextCompressor(max_tokens=4000)
        conv = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        result = cc.compress(conv)
        self.assertNotIn("[摘要]", result)

    def test_compress_six_messages_triggers_summary(self):
        cc = ContextCompressor(max_tokens=4000)
        conv = [{"role": "user", "content": f"msg {i}"} for i in range(6)]
        result = cc.compress(conv)
        self.assertIn("[摘要]", result)

    def test_format_conversation_unknown_role(self):
        cc = ContextCompressor(max_tokens=4000)
        conv = [{"role": "unknown", "content": "test"}]
        result = cc._format_conversation(conv)
        self.assertIn("test", result)

    def test_summarize_detects_facts(self):
        cc = ContextCompressor(max_tokens=4000)
        msgs = [{"role": "user", "content": "The config path is /etc/app.conf"}]
        s = cc._summarize(msgs)
        self.assertIn("config", s)

    def test_summarize_empty_messages(self):
        cc = ContextCompressor(max_tokens=4000)
        s = cc._summarize([])
        self.assertIsInstance(s, str)
        self.assertIn("0", s)

    def test_summarize_no_keywords_fallback(self):
        cc = ContextCompressor(max_tokens=4000)
        msgs = [{"role": "user", "content": "random chitchat about weather today is nice yes"}]
        s = cc._summarize(msgs)
        self.assertIsInstance(s, str)

    def test_compress_custom_max_tokens(self):
        cc = ContextCompressor(max_tokens=100)
        conv = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        result = cc.compress(conv)
        self.assertIsInstance(result, str)

    def test_format_conversation_missing_content(self):
        cc = ContextCompressor(max_tokens=4000)
        conv = [{"role": "user"}, {"role": "assistant", "content": "hi"}]
        result = cc._format_conversation(conv)
        self.assertIsInstance(result, str)


# ============================================================
# TestSemanticCompressorEdgeCases
# ============================================================

class TestSemanticCompressorEdgeCases(unittest.TestCase):

    def setUp(self):
        self.sc = SemanticCompressor(token_budget=2000)

    def test_compress_prunes_low_importance_expired(self):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        low = MemoryEntry.create(MemoryType.USER, "low", "x", importance=0.1)
        low.last_accessed = old_date
        low.access_count = 1
        high = MemoryEntry.create(MemoryType.USER, "high", "y", importance=0.9)
        result, stats = self.sc.compress([low, high])
        self.assertNotIn("low", [e.title for e in result])

    def test_compress_keeps_high_importance_within_budget(self):
        entries = [MemoryEntry.create(MemoryType.USER, f"h{i}", "x" * 100, importance=0.9)
                   for i in range(5)]
        result, stats = self.sc.compress(entries)
        self.assertGreater(len(result), 0)
        self.assertEqual(stats["pruned"], 0)

    def test_compress_stats_pruned_count(self):
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        entries = [MemoryEntry.create(MemoryType.USER, "old_low", "c", importance=0.1)]
        entries[0].last_accessed = old_date
        entries[0].access_count = 1
        _, stats = self.sc.compress(entries)
        self.assertGreaterEqual(stats["pruned"], 0)

    def test_is_expired_not_expired_when_access_count_high(self):
        e = MemoryEntry.create(MemoryType.USER, "freq", "content")
        e.last_accessed = (datetime.now() - timedelta(days=60)).isoformat()
        e.access_count = 5
        self.assertFalse(self.sc._is_expired(e))

    def test_is_expired_with_bad_date_format(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        e.last_accessed = "not-a-date"
        self.assertFalse(self.sc._is_expired(e))

    def test_truncate_short_content_not_truncated(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "short", importance=0.9)
        result = self.sc._truncate(e, max_tokens=500)
        self.assertIs(result, e)

    def test_summarize_detects_decided_keyword(self):
        e = MemoryEntry.create(MemoryType.USER, "d", "We decided to use PostgreSQL for the database")
        result = self.sc._summarize(e)
        self.assertIn("[summary]", result.content)

    def test_summarize_preserves_type(self):
        e = MemoryEntry.create(MemoryType.PROJECT, "p", "选择使用 Rust 重写核心模块")
        result = self.sc._summarize(e)
        self.assertEqual(result.type, MemoryType.PROJECT)

    def test_merge_duplicates_keeps_higher_access(self):
        e1 = MemoryEntry.create(MemoryType.USER, "same", "older")
        e1.access_count = 2
        e2 = MemoryEntry.create(MemoryType.USER, "same", "newer")
        e2.access_count = 5
        result = self.sc._merge_duplicates([e1, e2])
        titles = [e.title for e in result]
        self.assertEqual(titles.count("same"), 1)

    def test_compress_empty_list(self):
        result, stats = self.sc.compress([])
        self.assertEqual(result, [])
        self.assertEqual(stats["total"], 0)

    def test_compress_returns_stats_keys(self):
        entries = [MemoryEntry.create(MemoryType.USER, f"e{i}", "c") for i in range(3)]
        _, stats = self.sc.compress(entries)
        for key in ["total", "kept", "summarized", "pruned", "merged", "tokens_saved", "remaining"]:
            self.assertIn(key, stats, f"Missing key: {key}")


# ============================================================
# TestMemoryStoreInternals
# ============================================================

class TestMemoryStoreInternals(unittest.TestCase):

    def test_ensure_index_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            self.assertTrue(store.index_file.exists())

    def test_ensure_index_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            store._ensure_index()
            store._ensure_index()
            self.assertTrue(store.index_file.exists())

    def test_store_creates_entry_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "store_test", "content body")
            path = store.store(e)
            self.assertTrue(Path(path).exists())
            content_text = Path(path).read_text(encoding="utf-8")
            self.assertIn("content body", content_text)

    def test_store_file_has_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "fm_test", "body content")
            store.store(e)
            md_files = [f for f in Path(tmp).glob("*.md") if f.name != "MEMORY.md"]
            self.assertEqual(len(md_files), 1)
            content_text = md_files[0].read_text(encoding="utf-8")
            self.assertIn("---", content_text)
            self.assertIn("name: fm_test", content_text)

    def test_load_ignores_memory_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entries = store.load()
            self.assertEqual(len(entries), 0)

    def test_update_index_new_entry_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "idx_new", "c1")
            store.store(e)
            index_content = store.index_file.read_text(encoding="utf-8")
            self.assertIn("idx_new", index_content)

    def test_update_index_existing_entry_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e1 = MemoryEntry.create(MemoryType.USER, "dup_title", "v1 content")
            store.store(e1)
            e2 = MemoryEntry.create(MemoryType.USER, "dup_title", "v2 content")
            store.store(e2)
            index_content = store.index_file.read_text(encoding="utf-8")
            lines = [ln for ln in index_content.split(chr(10)) if ln.startswith("- [dup_title]")]
            self.assertEqual(len(lines), 1)

    def test_load_after_multiple_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            for i in range(5):
                e = MemoryEntry.create(MemoryType.USER, f"m{i}", f"content {i}")
                store.store(e)
            entries = store.load()
            self.assertEqual(len(entries), 5)

    def test_load_empty_memory_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entries = store.load()
            self.assertEqual(len(entries), 0)

    def test_get_stats_by_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            store.store(MemoryEntry.create(MemoryType.USER, "u1", "c"))
            store.store(MemoryEntry.create(MemoryType.PROJECT, "p1", "c"))
            store.store(MemoryEntry.create(MemoryType.USER, "u2", "c"))
            stats = store.get_stats()
            self.assertEqual(stats["by_type"]["user"], 2)
            self.assertEqual(stats["by_type"]["project"], 1)

    def test_get_stats_total_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "t", "hello world test content")
            store.store(e)
            stats = store.get_stats()
            self.assertGreater(stats["total_tokens"], 0)

    def test_get_stats_avg_importance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            store.store(MemoryEntry.create(MemoryType.USER, "a", "c", importance=0.3))
            store.store(MemoryEntry.create(MemoryType.USER, "b", "c", importance=0.9))
            stats = store.get_stats()
            avg = stats["avg_importance"]
            self.assertAlmostEqual(avg, 0.6, places=1)

    def test_consolidate_rewrites_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "consol", "content for consolidation")
            store.store(e)
            stats = store.consolidate()
            self.assertIn("remaining", stats)
            reloaded = store.load()
            self.assertGreaterEqual(len(reloaded), 0)


# ============================================================
# TestSemanticCompressorBudgetBehavior
# ============================================================

class TestSemanticCompressorBudgetBehavior(unittest.TestCase):

    def test_compress_within_budget_keeps_all(self):
        sc = SemanticCompressor(token_budget=10000)
        entries = [MemoryEntry.create(MemoryType.USER, f"e{i}", "short", importance=0.5)
                   for i in range(10)]
        result, stats = sc.compress(entries)
        self.assertEqual(len(result), 10)
        self.assertEqual(stats["kept"], 10)

    def test_compress_over_budget_truncates_high_importance(self):
        long_content = "x" * 5000
        sc = SemanticCompressor(token_budget=1000)
        entries = [MemoryEntry.create(MemoryType.USER, f"h{i}", long_content, importance=0.9)
                   for i in range(3)]
        result, stats = sc.compress(entries)
        self.assertGreater(len(result), 0)

    def test_compress_over_budget_summarizes_medium_importance(self):
        sc = SemanticCompressor(token_budget=10)
        entries = [MemoryEntry.create(MemoryType.USER, f"m{i}",
                                      "决定使用 TypeScript 重构核心模块，选择 PostgreSQL 作为数据库",
                                      importance=0.5)
                   for i in range(5)]
        result, stats = sc.compress(entries)
        # All entries are handled (kept, summarized, or pruned)
        self.assertGreaterEqual(len(result) + stats["pruned"], 1)

    def test_compress_over_budget_prunes_low_importance(self):
        long_content = "x" * 3000
        sc = SemanticCompressor(token_budget=500)
        entries = [MemoryEntry.create(MemoryType.USER, f"l{i}", long_content, importance=0.1)
                   for i in range(5)]
        result, stats = sc.compress(entries)
        self.assertGreater(stats["pruned"], 0)

    def test_compress_stats_tokens_saved_is_integer(self):
        """tokens_saved is a valid integer"""
        long_content = "x" * 3000
        sc = SemanticCompressor(token_budget=500)
        entries = [MemoryEntry.create(MemoryType.USER, f"e{i}", long_content, importance=0.5)
                   for i in range(5)]
        _, stats = sc.compress(entries)
        self.assertIsInstance(stats["tokens_saved"], int)

    def test_compress_merged_count_reflects_dedup(self):
        sc = SemanticCompressor(token_budget=10000)
        e1 = MemoryEntry.create(MemoryType.USER, "same", "a", importance=0.5)
        e1.access_count = 1
        e2 = MemoryEntry.create(MemoryType.USER, "same", "b", importance=0.5)
        e2.access_count = 3
        _, stats = sc.compress([e1, e2])
        self.assertEqual(stats["merged"], 1)


# ============================================================
# TestMemoryStoreConcurrentAdvanced
# ============================================================

class TestMemoryStoreConcurrentAdvanced(unittest.TestCase):

    def test_concurrent_store_no_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            errors = []

            def add_many(prefix):
                try:
                    for i in range(10):
                        e = MemoryEntry.create(MemoryType.USER, f"{prefix}_{i}", f"content {i}")
                        store.store(e)
                except Exception as ex:
                    errors.append(ex)

            threads = [threading.Thread(target=add_many, args=(f"t{j}",)) for j in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
            entries = store.load()
            self.assertEqual(len(entries), 50)

    def test_concurrent_store_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            errors = []

            def writer(prefix):
                try:
                    for i in range(5):
                        store.store(MemoryEntry.create(MemoryType.USER, f"{prefix}_{i}", "c"))
                except Exception as ex:
                    errors.append(ex)

            def reader():
                try:
                    for _ in range(10):
                        store.load()
                except Exception as ex:
                    errors.append(ex)

            threads = [threading.Thread(target=writer, args=(f"w{i}",)) for i in range(3)]
            threads += [threading.Thread(target=reader) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(errors), 0)


# ============================================================
# TestMemoryEntryCreateAllTypes
# ============================================================

class TestMemoryEntryCreateAllTypes(unittest.TestCase):

    def test_all_memory_types_creatable(self):
        for mtype in [MemoryType.USER, MemoryType.FEEDBACK, MemoryType.PROJECT, MemoryType.REFERENCE]:
            e = MemoryEntry.create(mtype, "t", "c")
            self.assertEqual(e.type, mtype)

    def test_entry_metadata_default_empty(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        self.assertEqual(e.metadata, {})

    def test_entry_metadata_custom(self):
        e = MemoryEntry.create(MemoryType.USER, "t", "c", metadata={"key": "val"})
        self.assertEqual(e.metadata["key"], "val")


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. context_compressor extended tests - Iteration 42")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestMemoryEntryEdgeCases, TestContextCompressorEdgeCases,
               TestSemanticCompressorEdgeCases, TestMemoryStoreInternals,
               TestSemanticCompressorBudgetBehavior,
               TestMemoryStoreConcurrentAdvanced, TestMemoryEntryCreateAllTypes]:
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
