"""
J.A.R.V.I.S. 测试套件 - Iteration 2
运行: python tests/run_all.py
"""
import unittest, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from core.brain.context_compressor import ContextCompressor, MemoryStore, MemoryEntry, MemoryType
from core.kernel.ollama_manager import OllamaManager, OllamaModel


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
        self.td = Path(".test-mem")
        self.store = MemoryStore(memory_dir=str(self.td))

    def tearDown(self):
        import shutil
        if self.td.exists():
            shutil.rmtree(self.td)

    def test_store_load(self):
        e = MemoryEntry.create(MemoryType.USER, "t1", "c1", tags=["t"])
        p = self.store.store(e)
        self.assertTrue(Path(p).exists())
        entries = self.store.load()
        self.assertEqual(len(entries), 1)

    def test_index(self):
        e = MemoryEntry.create(MemoryType.PROJECT, "idx", "content")
        self.store.store(e)
        self.assertIn("idx", self.store.index_file.read_text())

    def test_consolidate(self):
        e1 = MemoryEntry.create(MemoryType.USER, "same", "a")
        e2 = MemoryEntry.create(MemoryType.USER, "same", "b")
        self.store.store(e1)
        self.store.store(e2)
        stats = self.store.consolidate()
        self.assertGreaterEqual(stats["merged"], 0)


class TestOllamaManager(unittest.TestCase):
    def test_model(self):
        m = OllamaModel(name="llama3", size="4000000000", digest="abc", modified_at="2026-07-08")
        self.assertEqual(m.name, "llama3")


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.td = Path(".test-int")
        self.td.mkdir(exist_ok=True)

    def tearDown(self):
        import shutil
        if self.td.exists():
            shutil.rmtree(self.td)

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
        print(f"压缩: {ms:.1f}ms")

    def test_store_speed(self):
        s = MemoryStore(memory_dir=".test-perf")
        s.memory_dir.mkdir(exist_ok=True)
        t0 = time.time()
        for i in range(10):
            s.store(MemoryEntry.create(MemoryType.USER, f"t{i}", f"c{i}"))
        ms = (time.time() - t0) * 1000
        self.assertLess(ms, 500)
        print(f"存储: {ms:.1f}ms")
        import shutil; shutil.rmtree(s.memory_dir)


class TestTerminalExecutor(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from core.kernel.terminal_executor import TerminalExecutor, TerminalCommand, CommandRisk
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
        self.assertIn("拦截", r.stderr)

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


class TestEventBus(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from core.kernel.event_bus import EventBus
        self.bus = EventBus(100)

    def test_emit(self):
        buf = []
        self.bus.subscribe("e", lambda x: buf.append(x.payload))
        self.bus.emit("e", {"v": 1})
        self.assertEqual(buf[0]["v"], 1)

    def test_unsub(self):
        buf = []
        sid = self.bus.subscribe("e", lambda x: buf.append(x.payload))
        self.bus.emit("e", {})
        self.assertEqual(len(buf), 1)
        self.bus.unsubscribe(sid)
        self.bus.emit("e", {})
        self.assertEqual(len(buf), 1)

    def test_wildcard(self):
        buf = []
        self.bus.subscribe("*", lambda x: buf.append(x.type))
        self.bus.emit("a", {})
        self.bus.emit("b", {})
        self.assertEqual(len(buf), 2)

    def test_history(self):
        self.bus.emit("x", {})
        self.bus.emit("y", {})
        h = self.bus.get_history()
        self.assertEqual(len(h), 2)

    def test_once(self):
        n = [0]
        self.bus.subscribe("o", lambda e: n.__setitem__(0, n[0] + 1), True)
        self.bus.emit("o", {})
        self.bus.emit("o", {})
        self.assertEqual(n[0], 1)


class TestMultiAgent(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from core.brain.multi_agent_protocol import MultiAgentOrchestrator, Agent
        self.orch = MultiAgentOrchestrator(max_rounds=2)
        self.Agent = Agent

    def test_register(self):
        a = self.Agent(id="a1", name="T", role="x", capabilities=["coding"],
                  status="idle", system_prompt="", tools=[])
        self.orch.register_agent(a)
        self.assertEqual(len(self.orch.get_agents()), 1)

    def test_find(self):
        a = self.Agent(id="a1", name="Coder", role="c", capabilities=["coding"],
                  status="idle", system_prompt="", tools=[])
        self.orch.register_agent(a)
        f = self.orch.find_agent_by_capability("coding")
        self.assertIsNotNone(f)
        self.assertEqual(f.name, "Coder")

    def test_unregister(self):
        a = self.Agent(id="a1", name="T", role="x", capabilities=[],
                  status="idle", system_prompt="", tools=[])
        self.orch.register_agent(a)
        self.assertTrue(self.orch.unregister_agent("a1"))
        self.assertEqual(len(self.orch.get_agents()), 0)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. 测试套件 - Iteration 2 (7 类)")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for tc in [TestContextCompressor, TestMemoryStore, TestOllamaManager,
               TestIntegration, TestPerformance, TestTerminalExecutor,
               TestEventBus, TestMultiAgent]:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"结果: {total} 个测试, 通过 {passed}, 失败 {len(result.failures)}, 错误 {len(result.errors)}")
    print("=" * 60)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
