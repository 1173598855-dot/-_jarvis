"""Extended tests for context_compressor.py - Iteration 53"""
import sys
import tempfile
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.context_compressor import (
    ContextCompressor,
    MemoryEntry,
    MemoryStore,
    MemoryType,
    SemanticCompressor,
)


class TestMemoryStoreLoadFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(memory_dir=self.tmp, token_budget=4000)

    def test_load_empty_returns_list(self):
        entries = self.store.load()
        self.assertIsInstance(entries, list)

    def test_load_filters_user_type(self):
        self.store.store(MemoryEntry.create(MemoryType.USER, "u1", "user content"))
        self.store.store(MemoryEntry.create(MemoryType.PROJECT, "p1", "project content"))
        entries = self.store.load(memory_type=MemoryType.USER)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].type, MemoryType.USER)

    def test_load_filters_project_type(self):
        self.store.store(MemoryEntry.create(MemoryType.USER, "u1", "user content"))
        self.store.store(MemoryEntry.create(MemoryType.PROJECT, "p1", "project content"))
        entries = self.store.load(memory_type=MemoryType.PROJECT)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].type, MemoryType.PROJECT)

    def test_load_none_type_returns_all(self):
        self.store.store(MemoryEntry.create(MemoryType.USER, "u1", "user content"))
        self.store.store(MemoryEntry.create(MemoryType.REFERENCE, "r1", "ref content"))
        entries = self.store.load(memory_type=None)
        self.assertEqual(len(entries), 2)

    def test_load_empty_dir_returns_empty_list(self):
        empty_tmp = tempfile.mkdtemp()
        empty_store = MemoryStore(memory_dir=empty_tmp)
        entries = empty_store.load()
        self.assertEqual(entries, [])


class TestMemoryStoreConsolidate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(memory_dir=self.tmp, token_budget=4000)

    def test_consolidate_returns_valid_stats_keys(self):
        self.store.store(MemoryEntry.create(MemoryType.USER, "s1", "content 1"))
        self.store.store(MemoryEntry.create(MemoryType.PROJECT, "s2", "content 2"))
        stats = self.store.consolidate()
        for key in ["total", "merged", "pruned", "compressed", "remaining", "tokens_saved"]:
            self.assertIn(key, stats)

    def test_consolidate_total_equals_stored(self):
        self.store.store(MemoryEntry.create(MemoryType.USER, "s1", "content 1"))
        self.store.store(MemoryEntry.create(MemoryType.USER, "s2", "content 2"))
        stats = self.store.consolidate()
        self.assertEqual(stats["total"], 2)

    def test_consolidate_empty_store_returns_zero_stats(self):
        stats = self.store.consolidate()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["remaining"], 0)


class TestMemoryStoreGetStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(memory_dir=self.tmp, token_budget=4000)

    def test_get_stats_empty_store(self):
        stats = self.store.get_stats()
        self.assertEqual(stats["total"], 0)
        self.assertIn("by_type", stats)

    def test_get_stats_counts_entries(self):
        self.store.store(MemoryEntry.create(MemoryType.USER, "s1", "user 1"))
        self.store.store(MemoryEntry.create(MemoryType.PROJECT, "s2", "project 1"))
        stats = self.store.get_stats()
        self.assertEqual(stats["total"], 2)
        self.assertIn("user", stats["by_type"])
        self.assertIn("project", stats["by_type"])

    def test_get_stats_tokens_sums(self):
        self.store.store(MemoryEntry.create(MemoryType.USER, "s1", "hello world test"))
        stats = self.store.get_stats()
        self.assertGreaterEqual(stats["total_tokens"], 0)


class TestMemoryStoreConcurrent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(memory_dir=self.tmp, token_budget=4000)

    def test_concurrent_store_no_corruption(self):
        import threading
        errors = []
        def store_entry(i):
            try:
                self.store.store(MemoryEntry.create(
                    MemoryType.USER, "c" + str(i), "content " + str(i)))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=store_entry, args=(i,)) for i in range(5)]
        for t_idx in range(len(threads)):
            threads[t_idx].start()
        for t_idx in range(len(threads)):
            threads[t_idx].join()
        self.assertEqual(len(errors), 0)
        entries = self.store.load()
        self.assertEqual(len(entries), 5)

    def test_concurrent_store_and_load(self):
        import threading
        self.store.store(MemoryEntry.create(MemoryType.USER, "base", "base content"))
        load_counts = []
        def load_entry():
            entries = self.store.load()
            load_counts.append(len(entries))
        threads = [threading.Thread(target=load_entry) for _ in range(3)]
        for t_idx in range(len(threads)):
            threads[t_idx].start()
        for t_idx in range(len(threads)):
            threads[t_idx].join()
        for count in load_counts:
            self.assertGreaterEqual(count, 1)


class TestContextCompressorInit(unittest.TestCase):
    def test_default_max_tokens(self):
        cc = ContextCompressor()
        self.assertEqual(cc.max_tokens, 4000)

    def test_custom_max_tokens(self):
        cc = ContextCompressor(max_tokens=2000)
        self.assertEqual(cc.max_tokens, 2000)

    def test_compress_empty_conversation(self):
        cc = ContextCompressor(max_tokens=100)
        result = cc.compress([])
        self.assertIsInstance(result, str)


class TestSemanticCompressorInit(unittest.TestCase):
    def test_default_token_budget(self):
        sc = SemanticCompressor()
        self.assertEqual(sc.token_budget, 4000)

    def test_custom_token_budget(self):
        sc = SemanticCompressor(token_budget=2000)
        self.assertEqual(sc.token_budget, 2000)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. context_compressor extended tests v2 - Iteration 53")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestMemoryStoreLoadFilter, TestMemoryStoreConsolidate,
        TestMemoryStoreGetStats, TestMemoryStoreConcurrent,
        TestContextCompressorInit, TestSemanticCompressorInit,
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
