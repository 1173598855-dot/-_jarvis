"""
Context Compressor tests - Phase 11 memory system
Run: python3 tests/test_context_compressor.py
"""
import inspect
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.context_compressor import (
    ContextCompressor,
    MemoryEntry,
    MemoryStore,
    MemoryType,
    SemanticCompressor,
)


class TestMemoryEntry(unittest.TestCase):
    def test_create_user(self):
        e = MemoryEntry.create(MemoryType.USER, "t1", "content", tags=["a"])
        self.assertEqual(e.type, MemoryType.USER)
        self.assertEqual(e.title, "t1")
        self.assertEqual(e.content, "content")
        self.assertIn("a", e.tags)
        self.assertFalse(e.compressed)

    def test_default_importance(self):
        """importance defaults to 0.5 per implementation"""
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        self.assertEqual(e.importance, 0.5)

    def test_estimate_tokens_short(self):
        t = MemoryEntry._estimate_tokens("hello")
        self.assertGreaterEqual(t, 1)

    def test_estimate_tokens_long(self):
        t = MemoryEntry._estimate_tokens("word " * 1000)
        self.assertGreater(t, 500)


class TestContextCompressor(unittest.TestCase):
    def setUp(self):
        self.cc = ContextCompressor(max_tokens=4000)

    def test_compress_short_no_summary(self):
        conv = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        r = self.cc.compress(conv)
        self.assertIn("hi", r)
        self.assertNotIn("[摘要]", r)

    def test_compress_long_with_summary(self):
        conv = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        r = self.cc.compress(conv)
        self.assertIn("[摘要]", r)

    def test_summarize_returns_string(self):
        msgs = [{"role": "user", "content": "决定使用 TS 开发前端"}]
        s = self.cc._summarize(msgs)
        self.assertIsInstance(s, str)
        self.assertIn("决定", s)

    def test_format_conversation(self):
        conv = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
        r = self.cc._format_conversation(conv)
        self.assertIn("user", r)
        self.assertIn("q", r)


class TestSemanticCompressor(unittest.TestCase):
    def setUp(self):
        self.sc = SemanticCompressor(token_budget=4000)

    def test_compress_returns_list(self):
        entries = [MemoryEntry.create(MemoryType.USER, f"e{i}", f"c{i}") for i in range(5)]
        result, stats = self.sc.compress(entries)
        self.assertIsInstance(result, list)

    def test_compress_stats_keys(self):
        """Stats uses keys: total, kept, summarized, pruned, merged, tokens_saved, remaining"""
        entries = [MemoryEntry.create(MemoryType.USER, f"e{i}", f"c{i}") for i in range(5)]
        _, stats = self.sc.compress(entries)
        self.assertIn("total", stats)
        self.assertIn("kept", stats)
        self.assertIn("remaining", stats)
        self.assertEqual(stats["total"], 5)

    def test_is_expired_recent(self):
        from datetime import datetime, timedelta
        e = MemoryEntry.create(MemoryType.USER, "t", "c")
        e.created_at = (datetime.now() - timedelta(days=1)).isoformat()
        self.assertFalse(self.sc._is_expired(e))

    def test_truncate_entry(self):
        long_content = "x" * 2000
        e = MemoryEntry.create(MemoryType.USER, "t", long_content)
        result = self.sc._truncate(e, max_tokens=50)
        self.assertIsNotNone(result)

    def test_merge_duplicates(self):
        e1 = MemoryEntry.create(MemoryType.USER, "same", "a")
        e2 = MemoryEntry.create(MemoryType.USER, "same", "b")
        result = self.sc._merge_duplicates([e1, e2])
        self.assertIsInstance(result, list)


class TestMemoryStore(unittest.TestCase):
    """Each test uses tempfile.TemporaryDirectory to ensure clean state"""

    def test_store_creates_files(self):
        """store() creates MEMORY.md + entry file in memory_dir"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "t1", "c1", tags=["t"])
            p = store.store(e)
            self.assertTrue(Path(p).exists())
            # After store: MEMORY.md + 1 entry file = 2 md files
            md_files = list(Path(tmp).glob("*.md"))
            self.assertEqual(len(md_files), 2)

    def test_read_only_store_does_not_create_missing_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "missing"
            self.assertIn("read_only", inspect.signature(MemoryStore).parameters)

            store = MemoryStore(memory_dir=str(memory_dir), read_only=True)

            self.assertEqual(store.load(), [])
            self.assertFalse(memory_dir.exists())

    def test_read_only_load_bounds_scans_files_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
            payload = (
                "---\nname: Match\ntype: user\nimportance: 0.5\n---\n\nneedle"
            )
            for index in range(4):
                (memory_dir / f"user_{index}.md").write_bytes(payload.encode("utf-8"))
            oversized = memory_dir / "user_oversized.md"
            oversized.write_bytes(b"x" * 256)
            self.assertIn("read_only", inspect.signature(MemoryStore).parameters)
            store = MemoryStore(memory_dir=str(memory_dir), read_only=True)

            file_limited = store.load(
                max_directory_entries=10,
                max_files=2,
                max_file_bytes=1024,
                max_total_bytes=4096,
            )
            directory_limited = store.load(
                max_directory_entries=1,
                max_files=10,
                max_file_bytes=1024,
                max_total_bytes=4096,
            )
            byte_limited = store.load(
                max_directory_entries=10,
                max_files=10,
                max_file_bytes=128,
                max_total_bytes=len(payload.encode("utf-8")),
            )

            self.assertEqual(len(file_limited), 2)
            self.assertLessEqual(len(directory_limited), 1)
            self.assertEqual(len(byte_limited), 1)
            self.assertTrue(all(entry.title == "Match" for entry in byte_limited))

    def test_read_only_load_skips_invalid_metadata_and_keeps_valid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            invalid = "---\nname: Broken\ntype: invalid\n---\n\nneedle"
            valid = "---\nname: Valid\ntype: user\n---\n\nneedle"
            (memory_dir / "user_bad.md").write_bytes(invalid.encode("utf-8"))
            (memory_dir / "user_good.md").write_bytes(valid.encode("utf-8"))
            store = MemoryStore(memory_dir=str(memory_dir), read_only=True)

            try:
                entries = store.load(
                    max_directory_entries=10,
                    max_files=10,
                    max_file_bytes=1024,
                    max_total_bytes=4096,
                )
            except ValueError as error:
                self.fail(f"invalid read-only candidate was not skipped: {error}")

            self.assertEqual([entry.title for entry in entries], ["Valid"])

    def test_writable_load_rejects_read_only_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            with self.assertRaisesRegex(ValueError, "read-only"):
                store.load(max_files=1)

    def test_load_returns_correct_count(self):
        """Store 1 entry, load returns exactly 1 (MEMORY.md is excluded)"""
        uid = uuid.uuid4().hex[:6]
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, f"t1_{uid}", "c1", tags=["t"])
            store.store(e)
            entries = store.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, f"t1_{uid}")

    def test_load_filtered_by_type(self):
        """Filter by MemoryType.USER returns only USER entries"""
        uid = uuid.uuid4().hex[:6]
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e1 = MemoryEntry.create(MemoryType.USER, f"u1_{uid}", "c1")
            e2 = MemoryEntry.create(MemoryType.PROJECT, f"p1_{uid}", "c2")
            store.store(e1)
            store.store(e2)
            user_entries = store.load(MemoryType.USER)
            self.assertEqual(len(user_entries), 1)
            self.assertEqual(user_entries[0].title, f"u1_{uid}")

    def test_delete_probe_removes_exact_entry_file_and_index_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                ".test-local-integration-probe",
                "temporary",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))

            deleted = store.delete_probe(
                MemoryType.PROJECT,
                entry.id,
                "secret",
            )

            self.assertTrue(deleted)
            self.assertFalse(path.exists())
            self.assertNotIn(entry.id, store.index_file.read_text(encoding="utf-8"))
            self.assertEqual(store.load(), [])

    def test_delete_probe_rejects_invalid_entry_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)

            self.assertFalse(store.delete_probe(MemoryType.PROJECT, "../MEMORY", "secret"))

    def test_delete_probe_rejects_regular_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entry = MemoryEntry.create(
                MemoryType.PROJECT,
                "real user memory",
                "keep this",
                metadata={"probe_cleanup_token": "secret"},
            )
            path = Path(store.store(entry))

            self.assertFalse(store.delete_probe(MemoryType.PROJECT, entry.id, "secret"))
            self.assertTrue(path.exists())

    def test_delete_probe_targets_one_memory_type_when_ids_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            entries = [
                MemoryEntry.create(
                    memory_type,
                    ".test-local-integration-collision",
                    "same content",
                    metadata={"probe_cleanup_token": "secret"},
                )
                for memory_type in (MemoryType.USER, MemoryType.PROJECT)
            ]
            paths = [Path(store.store(entry)) for entry in entries]
            self.assertEqual(entries[0].id, entries[1].id)

            deleted = store.delete_probe(
                MemoryType.PROJECT,
                entries[1].id,
                "secret",
            )

            self.assertTrue(deleted)
            self.assertTrue(paths[0].exists())
            self.assertFalse(paths[1].exists())

    def test_index_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "idx", "content")
            store.store(e)
            self.assertTrue(store.index_file.exists())

    def test_consolidate_no_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            uid = uuid.uuid4().hex[:6]
            e1 = MemoryEntry.create(MemoryType.USER, f"s1_{uid}", "a")
            e2 = MemoryEntry.create(MemoryType.USER, f"s2_{uid}", "b")
            store.store(e1)
            store.store(e2)
            stats = store.consolidate()
            self.assertIn("merged", stats)

    def test_get_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "st", "content")
            store.store(e)
            stats = store.get_stats()
            self.assertIn("total", stats)
            self.assertGreaterEqual(stats["total"], 1)


class TestMemoryStoreConcurrent(unittest.TestCase):
    """Thread safety test for MemoryStore"""

    def test_concurrent_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            errors = []

            def add_many(prefix):
                try:
                    for i in range(5):
                        e = MemoryEntry.create(MemoryType.USER, f"{prefix}_{i}", f"c{i}")
                        store.store(e)
                except Exception as ex:
                    errors.append(ex)

            threads = [threading.Thread(target=add_many, args=(f"t{j}",)) for j in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(errors), 0, f"Thread errors: {errors}")

class TestSemanticCompressorSummarize(unittest.TestCase):
    """_summarize(entry) returns MemoryEntry with summarized=True"""

    def setUp(self):
        self.sc = SemanticCompressor(token_budget=4000)

    def test_summarize_decision_content(self):
        """_summarize extracts decision sentences"""
        e = MemoryEntry.create(
            MemoryType.USER, "dec", "决定使用 TS 开发前端，因为类型安全",
            tags=["decision"]
        )
        result = self.sc._summarize(e)
        self.assertIsInstance(result, MemoryEntry)
        self.assertTrue(result.compressed)
        self.assertIn("[summary]", result.title)
        self.assertIn("summarized", result.metadata)
        self.assertIn("original_length", result.metadata)
        self.assertEqual(result.parent_id, e.id)

    def test_summarize_reduces_tokens(self):
        """_summarize should reduce token count vs original"""
        long_content = "这是一个很长的内容。" * 50
        e = MemoryEntry.create(MemoryType.USER, "long", long_content)
        original_tokens = e.token_count
        result = self.sc._summarize(e)
        self.assertLess(result.token_count, original_tokens)

    def test_summarize_no_keywords(self):
        """_summarize with no keyword sentences uses first 3 sentences"""
        e = MemoryEntry.create(
            MemoryType.USER, "plain", "第一句。第二句。第三句。第四句。"
        )
        result = self.sc._summarize(e)
        self.assertIn("[summary]", result.title)
        self.assertTrue(result.compressed)


class TestMemoryStoreEnsureIndex(unittest.TestCase):
    """_ensure_index() creates MEMORY.md if not present"""

    def test_ensure_index_creates_file_when_missing(self):
        """_ensure_index creates empty MEMORY.md when not present"""
        with tempfile.TemporaryDirectory() as tmp:
            _ = MemoryStore(memory_dir=tmp)
            idx = Path(tmp) / "MEMORY.md"
            self.assertTrue(idx.exists())
            content_text = idx.read_text(encoding="utf-8")
            expected = "# Memory Index" + chr(10)*2
            self.assertEqual(content_text, expected)

    def test_ensure_index_idempotent(self):
        """_ensure_index does not overwrite existing MEMORY.md"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            idx = Path(tmp) / "MEMORY.md"
            existing_content = "# Custom Index" + chr(10) + "-existing line" + chr(10)
            idx.write_text(existing_content, encoding="utf-8")
            store._ensure_index()
            self.assertEqual(idx.read_text(encoding="utf-8"), existing_content)


class TestMemoryStoreUpdateIndex(unittest.TestCase):
    """_update_index() updates or appends to MEMORY.md index"""

    def test_update_index_new_entry_appends(self):
        """_update_index appends new entry line when title not in index"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e = MemoryEntry.create(MemoryType.USER, "new_title", "some content")
            store._update_index(e, "new_title.md")
            idx = Path(tmp) / "MEMORY.md"
            content_text = idx.read_text(encoding="utf-8")
            self.assertIn("new_title", content_text)
            self.assertIn("new_title.md", content_text)

    def test_update_index_existing_entry_replaces(self):
        """_update_index replaces line when title already in index"""
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(memory_dir=tmp)
            e1 = MemoryEntry.create(MemoryType.USER, "title_a", "content a")
            e2 = MemoryEntry.create(MemoryType.USER, "title_a", "content b updated")
            store.store(e1)
            store._update_index(e2, "title_a.md")
            idx = Path(tmp) / "MEMORY.md"
            lines = idx.read_text(encoding="utf-8").splitlines()
            title_a_lines = [ln for ln in lines if "title_a" in ln and ln.startswith("-")]
            self.assertEqual(len(title_a_lines), 1)
            self.assertIn("updated", title_a_lines[0])

def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. context_compressor tests - Iteration 30")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestMemoryEntry, TestContextCompressor, TestSemanticCompressor,
               TestSemanticCompressorSummarize, TestMemoryStore,
               TestMemoryStoreEnsureIndex, TestMemoryStoreUpdateIndex,
               TestMemoryStoreConcurrent]:
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
