"""
Test Orchestrator - multi-agent dispatch, history, lifecycle
Run: python3 tests/test_orchestrator.py
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.orchestrator import (
    AgentResult,
    AgentTask,
    Orchestrator,
)


def make_orchestrator():
    return Orchestrator(default_timeout=10)


def simple_handler(task):
    return {"status": "ok", "task_id": task.task_id}


def slow_handler(task):
    time.sleep(0.05)
    return {"done": True}


def failing_handler(task):
    raise RuntimeError("handler failed")


class TestOrchestratorInit(unittest.TestCase):

    def test_empty_registry(self):
        orch = make_orchestrator()
        self.assertEqual(len(orch.list_agents()), 0)

    def test_initial_stats_zero(self):
        orch = make_orchestrator()
        stats = orch.get_stats()
        self.assertEqual(stats["total_dispatched"], 0)
        self.assertEqual(stats["total_success"], 0)

    def test_empty_history(self):
        orch = make_orchestrator()
        self.assertEqual(orch.collect(), [])


class TestOrchestratorRegister(unittest.TestCase):

    def test_register_returns_self(self):
        orch = make_orchestrator()
        result = orch.register_in_process("agent1", simple_handler)
        self.assertIs(result, orch)

    def test_register_list_agents(self):
        orch = make_orchestrator()
        orch.register_in_process("agent1", simple_handler, capabilities=["code"])
        agents = orch.list_agents()
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].name, "agent1")

    def test_register_reregister_replaces(self):
        orch = make_orchestrator()
        orch.register_in_process("agent1", simple_handler)
        orch.register_in_process("agent1", failing_handler)  # re-register
        agents = orch.list_agents()
        self.assertEqual(len(agents), 1)

    def test_register_with_capabilities(self):
        orch = make_orchestrator()
        orch.register_in_process("coder", simple_handler, capabilities=["coding", "review"])
        agents = orch.list_agents()
        self.assertIn("coding", agents[0].capabilities)


class TestOrchestratorDispatch(unittest.TestCase):

    def setUp(self):
        self.orch = make_orchestrator()
        self.orch.register_in_process("worker", simple_handler, capabilities=["code"])

    def test_dispatch_success(self):
        task = AgentTask(task_id="t1", agent_name="worker", prompt="do thing")
        result = self.orch.dispatch(task)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.task_id, "t1")

    def test_dispatch_unknown_agent(self):
        task = AgentTask(task_id="t2", agent_name="ghost", prompt="hi")
        result = self.orch.dispatch(task)
        self.assertEqual(result.status, "error")
        self.assertIn("not found", result.error)

    def test_dispatch_records_history(self):
        task = AgentTask(task_id="t3", agent_name="worker", prompt="hi")
        self.orch.dispatch(task)
        history = self.orch.collect()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].task_id, "t3")

    def test_dispatch_updates_stats(self):
        task = AgentTask(task_id="t4", agent_name="worker", prompt="hi")
        self.orch.dispatch(task)
        stats = self.orch.get_stats()
        self.assertEqual(stats["total_dispatched"], 1)
        self.assertEqual(stats["total_success"], 1)

    def test_dispatch_handler_exception(self):
        orch = make_orchestrator()
        orch.register_in_process("bad", failing_handler)
        task = AgentTask(task_id="t5", agent_name="bad", prompt="crash")
        result = orch.dispatch(task)
        self.assertEqual(result.status, "error")
        self.assertIn("handler failed", result.error)

    def test_dispatch_after_shutdown(self):
        self.orch.shutdown()
        task = AgentTask(task_id="t6", agent_name="worker", prompt="hi")
        result = self.orch.dispatch(task)
        self.assertEqual(result.status, "error")
        self.assertIn("shutting down", result.error)


class TestOrchestratorCollect(unittest.TestCase):

    def test_collect_filter_by_agent_name(self):
        orch = make_orchestrator()
        orch.register_in_process("a", simple_handler)
        orch.register_in_process("b", simple_handler)
        orch.dispatch(AgentTask("t1", "a", "p"))
        orch.dispatch(AgentTask("t2", "b", "p"))
        orch.dispatch(AgentTask("t3", "a", "p"))
        results = orch.collect(agent_name="a")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r.agent_name, "a")

    def test_collect_limit(self):
        orch = make_orchestrator()
        orch.register_in_process("w", simple_handler)
        for i in range(10):
            orch.dispatch(AgentTask(f"t{i}", "w", "p"))
        results = orch.collect(limit=3)
        self.assertEqual(len(results), 3)

    def test_collect_filter_by_status(self):
        orch = make_orchestrator()
        orch.register_in_process("w", simple_handler)
        orch.register_in_process("f", failing_handler)
        orch.dispatch(AgentTask("ok1", "w", "p"))
        orch.dispatch(AgentTask("err1", "f", "p"))
        results = orch.collect(status="success")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "success")


class TestOrchestratorConcurrent(unittest.TestCase):

    def test_dispatch_concurrent_multiple_tasks(self):
        orch = make_orchestrator()
        orch.register_in_process("w", simple_handler)
        tasks = [AgentTask(f"ct{i}", "w", f"p{i}") for i in range(5)]
        results = orch.dispatch_concurrent(tasks)
        self.assertEqual(len(results), 5)
        self.assertEqual(len(results), 5)  # all tasks dispatched

    def test_dispatch_concurrent_no_agents_dropped(self):
        orch = make_orchestrator()
        orch.register_in_process("w", simple_handler)
        tasks = [AgentTask(f"c{i}", "w", "p") for i in range(8)]
        results = orch.dispatch_concurrent(tasks)
        self.assertEqual(len(results), 8)


class TestOrchestratorShutdown(unittest.TestCase):

    def test_shutdown_prevents_dispatch(self):
        orch = make_orchestrator()
        orch.register_in_process("w", simple_handler)
        orch.dispatch(AgentTask("pre", "w", "p"))  # ok before shutdown
        orch.shutdown()
        result = orch.dispatch(AgentTask("post", "w", "p"))
        self.assertEqual(result.status, "error")

    def test_get_stats_after_dispatch(self):
        orch = make_orchestrator()
        orch.register_in_process("w", simple_handler)
        orch.dispatch(AgentTask("t1", "w", "p"))
        stats = orch.get_stats()
        self.assertEqual(stats["total_dispatched"], 1)
        self.assertEqual(stats["total_success"], 1)
        self.assertEqual(stats["total_errors"], 0)


class TestAgentTaskResult(unittest.TestCase):

    def test_agent_result_to_dict(self):
        r = AgentResult(task_id="t1", agent_name="a", status="success",
                        result={"ok": True})
        d = r.to_dict()
        self.assertEqual(d["task_id"], "t1")
        self.assertEqual(d["status"], "success")
        self.assertIn("ok", d["result"])

    def test_agent_info_from_result(self):
        orch = make_orchestrator()
        orch.register_in_process("worker", simple_handler)
        result = orch.dispatch(AgentTask("t1", "worker", "p"))
        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.agent_name, "worker")

    def test_agent_task_defaults(self):
        t = AgentTask(task_id="x", agent_name="a", prompt="p")
        self.assertEqual(t.timeout, 30)
        self.assertEqual(t.priority, 1)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. orchestrator tests - Iteration 32")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestOrchestratorInit, TestOrchestratorRegister,
               TestOrchestratorDispatch, TestOrchestratorCollect,
               TestOrchestratorConcurrent, TestOrchestratorShutdown,
               TestAgentTaskResult]:
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
