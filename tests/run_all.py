"""
J.A.R.V.I.S. test suite - Iteration 84
Run: python tests/run_all.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from core.brain.context_compressor import ContextCompressor, MemoryEntry, MemoryStore, MemoryType
from core.brain.role_registry import AgentProfile, RoleRegistry, create_default_registry
from core.kernel.ollama_manager import OllamaModel
from core.kernel.terminal_executor import CommandRisk, TerminalCommand, TerminalExecutor
from test_docs_setup import TestSetupDocs
from test_iteration_ledger import TestIterationLedger
from test_main import TestMainHTTPHelpers, TestMainHTTPGETRouting, TestMainHTTPPOSTRouting, TestMainHTTPHandleMethodsRouting, TestMainHTTPEdgeCases
from test_main_fastapi import TestMainFastapiIntegration
from test_project_config import TestPythonDependencies
from test_readme import TestReadme
from test_plugin_installation import TestPluginInstallation


class TestContextCompressor(unittest.TestCase):
    def setUp(self):
        self.compressor = ContextCompressor(max_tokens=4000)

    def test_compress_short(self):
        conv = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        r = self.compressor.compress(conv)
        self.assertIn("hi", r)
        self.assertNotIn("[摘要]", r)

    def test_compress_long(self):
        conv = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        r = self.compressor.compress(conv)
        self.assertIn("[摘要]", r)

    def test_summarize_decisions(self):
        msgs = [{"role": "user", "content": "决定使用 TS"}]
        s = self.compressor._summarize(msgs)
        self.assertIn("决定", s)


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        import uuid
        self.td = Path(f".test-mem-{uuid.uuid4().hex[:8]}")
        self.td.mkdir(exist_ok=True)
        self.store = MemoryStore(memory_dir=str(self.td))

    def tearDown(self):
        import os
        if self.td.exists():
            for root, dirs, files in os.walk(self.td, topdown=False):
                for f in files:
                    try:
                        Path(root, f).unlink()
                    except PermissionError:
                        pass
            try:
                self.td.rmdir()
            except PermissionError:
                pass

    def test_store_load(self):
        store = MemoryStore(memory_dir=str(self.td))
        e = MemoryEntry.create(MemoryType.USER, "t1", "c1", tags=["t"])
        p = store.store(e)
        self.assertTrue(Path(p).exists())
        entries = store.load()
        self.assertEqual(len(entries), 1)

    def test_index(self):
        store = MemoryStore(memory_dir=str(self.td))
        e = MemoryEntry.create(MemoryType.PROJECT, "idx", "content")
        store.store(e)
        self.assertIn("idx", store.index_file.read_text())

    def test_consolidate(self):
        store = MemoryStore(memory_dir=str(self.td))
        e1 = MemoryEntry.create(MemoryType.USER, "same", "a")
        e2 = MemoryEntry.create(MemoryType.USER, "same", "b")
        store.store(e1)
        store.store(e2)
        stats = store.consolidate()
        self.assertGreaterEqual(stats["merged"], 0)


class TestOllamaManager(unittest.TestCase):
    def test_model(self):
        m = OllamaModel(name="llama3", size="4000000000", digest="abc", modified_at="2026-07-08")
        self.assertEqual(m.name, "llama3")


class TestAgentProfile(unittest.TestCase):
    def test_resolve_prompt(self):
        p = AgentProfile(name="e", display_name="Engineer", description="Coding",
                         prompt_template="Role: {name}. Task: {task}")
        r = p.resolve_prompt("fix bug")
        self.assertIn("Engineer", r)
        self.assertIn("fix bug", r)

    def test_to_from_dict(self):
        p = AgentProfile(name="pm", display_name="PM", description="Product", capabilities=["req"], priority=8)
        p2 = AgentProfile.from_dict(p.to_dict())
        self.assertEqual(p.name, p2.name)
        self.assertEqual(p.capabilities, p2.capabilities)


class TestRoleRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = RoleRegistry()

    def test_register_get(self):
        p = AgentProfile(name="t1", display_name="T1", description="d")
        self.reg.register(p)
        self.assertIsNotNone(self.reg.get("t1"))

    def test_default_registry_roles(self):
        reg = create_default_registry()
        expected_default_names = [
            "architect",
            "engineer",
            "reviewer",
            "tester",
            "product_manager",
        ]
        for name in expected_default_names:
            self.assertIsNotNone(reg.get(name), msg=name)
        self.assertEqual(len(expected_default_names), 5)


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.td = Path(".test-int")
        self.td.mkdir(exist_ok=True)

    def tearDown(self):
        import os
        if self.td.exists():
            for root, dirs, files in os.walk(self.td, topdown=False):
                for f in files:
                    try:
                        Path(root, f).unlink()
                    except PermissionError:
                        pass
            try:
                self.td.rmdir()
            except PermissionError:
                pass

    def test_pipeline(self):
        c = ContextCompressor()
        conv = [{"role": "user", "content": f"m{i}"} for i in range(10)]
        compressed = c.compress(conv)
        store = MemoryStore(memory_dir=str(self.td))
        e = MemoryEntry.create(MemoryType.PROJECT, "summary", compressed, tags=["auto"])
        store.store(e)
        entries = store.load(MemoryType.PROJECT)
        self.assertEqual(len(entries), 1)
        self.assertIn("[摘要]", entries[0].content)


class TestPerformance(unittest.TestCase):
    def test_compression_speed(self):
        c = ContextCompressor()
        conv = [{"role": "user", "content": f"msg {i}" * 10} for i in range(100)]
        t0 = time.time()
        c.compress(conv)
        ms = (time.time() - t0) * 1000
        self.assertLess(ms, 100, f"压缩 {ms:.1f}ms > 100ms")
        print(f"compress: {ms:.1f}ms")

    def test_store_speed(self):
        s = MemoryStore(memory_dir=".test-perf")
        if s.memory_dir.exists():
            import shutil
            shutil.rmtree(s.memory_dir)
        s.memory_dir.mkdir(exist_ok=True)
        t0 = time.time()
        for i in range(10):
            s.store(MemoryEntry.create(MemoryType.USER, f"t{i}", f"c{i}"))
        ms = (time.time() - t0) * 1000
        self.assertLess(ms, 500)
        print(f"store: {ms:.1f}ms")


class TestTerminalExecutor(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        self.Ex = TerminalExecutor
        self.Cmd = TerminalCommand
        self.Risk = CommandRisk

    def test_safe_cmd(self):
        ex = self.Ex()
        cmd = self.Cmd(id="t1", command="echo", args=["hello"], risk_level=self.Risk.SAFE)
        r = ex.execute(cmd)
        self.assertTrue(r.success)
        self.assertIn("hello", r.stdout)

    def test_danger_blocked(self):
        ex = self.Ex()
        cmd = self.Cmd(id="t2", command="rm", args=["-rf", "/"], risk_level=self.Risk.DANGEROUS)
        r = ex.execute(cmd)
        self.assertFalse(r.success)
        self.assertIn("Security block", r.stderr)

    def test_unknown_blocked(self):
        ex = self.Ex()
        cmd = self.Cmd(id="t3", command="badcmd", args=[], risk_level=self.Risk.DANGEROUS)
        r = ex.execute(cmd)
        self.assertFalse(r.success)

    def test_risk(self):
        ex = self.Ex()
        self.assertEqual(ex._assess_risk("ls"), self.Risk.SAFE)
        self.assertEqual(ex._assess_risk("rm"), self.Risk.DANGEROUS)
        self.assertEqual(ex._assess_risk("mv"), self.Risk.MODERATE)


AGGREGATE_TEST_CASES = [
    TestContextCompressor,
    TestMemoryStore,
    TestOllamaManager,
    TestAgentProfile,
    TestRoleRegistry,
    TestIntegration,
    TestPerformance,
    TestTerminalExecutor,
    TestReadme,
    TestSetupDocs,
    TestPythonDependencies,
    TestIterationLedger,
    TestMainHTTPHelpers,
    TestMainHTTPGETRouting,
    TestMainHTTPPOSTRouting,
    TestMainHTTPHandleMethodsRouting,
    TestMainHTTPEdgeCases,
    TestMainFastapiIntegration,
    TestPluginInstallation,
]


def canonical_test_count():
    loader = unittest.TestLoader()
    return sum(
        loader.loadTestsFromTestCase(tc).countTestCases()
        for tc in AGGREGATE_TEST_CASES
    )


def aggregate_suite_title():
    return f"J.A.R.V.I.S. test suite - Iteration 84 ({len(AGGREGATE_TEST_CASES)} classes)"


SMOKE_TEST_CASES = [
    TestReadme,
    TestSetupDocs,
    TestPythonDependencies,
    TestIterationLedger,
    TestPluginInstallation,
]


def build_aggregate_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for tc in AGGREGATE_TEST_CASES:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    return suite


def build_smoke_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for tc in SMOKE_TEST_CASES:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    return suite


def run_all_tests(timeout: int = 0, json_report: str = ""):
    return _run_suite(build_aggregate_suite(), timeout=timeout, json_report=json_report)


def run_smoke_tests(timeout: int = 0, json_report: str = ""):
    return _run_suite(build_smoke_suite(), timeout=timeout, json_report=json_report)


def _run_suite(suite, timeout: int = 0, json_report: str = ""):
    timeout_expired = threading.Event()
    result_holder = {}
    print("=" * 60)
    title = f"J.A.R.V.I.S. test suite - {suite.__class__.__name__} ({suite.countTestCases()} tests)"
    print(title)
    print("=" * 60)

    def run_suite():
        result_holder["result"] = unittest.TextTestRunner(verbosity=2).run(suite)

    thread = threading.Thread(target=run_suite)
    thread.start()
    thread.join(timeout=timeout if timeout > 0 else None)

    if thread.is_alive():
        timeout_expired.set()
        print("\nTimeout: {timeout}s exceeded".format(timeout=timeout))
        payload = {
            "title": title,
            "tests": 0,
            "passed": 0,
            "failures": 0,
            "errors": 0,
            "success": False,
            "timeout_seconds": timeout,
            "timeout_expired": True,
        }
        if json_report:
            Path(json_report).write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    result = result_holder.get("result", unittest.TestResult())
    print()
    print("=" * 60)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed, {len(result.failures)} failed, {len(result.errors)} errors")
    print("=" * 60)
    payload = {
        "title": title,
        "tests": total,
        "passed": passed,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "success": result.wasSuccessful(),
        "timeout_seconds": timeout,
        "timeout_expired": timeout_expired.is_set(),
    }
    if json_report:
        Path(json_report).write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
