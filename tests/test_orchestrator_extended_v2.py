"""Extended tests v2 for orchestrator.py - Iteration 57"""
import sys
import threading
import time
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.orchestrator import (
    AgentTask,
    Orchestrator,
)


class TestOrchestratorDispatchEdgeCases(unittest.TestCase):
    def test_dispatch_unknown_agent_returns_error_status(self):
        orch = Orchestrator()
        task = AgentTask(agent_name="nonexistent_agent_xyz", prompt="do it")
        result = orch.dispatch(task)
        self.assertEqual(result.status, "error")
        self.assertIn("not found", result.error)

    def test_dispatch_returns_duration_ms(self):
        orch = Orchestrator()
        orch.register("a", lambda t: "ok")
        task = AgentTask(agent_name="a", prompt="p")
        result = orch.dispatch(task)
        self.assertIsNotNone(result.duration_ms)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_dispatch_handler_returns_none(self):
        orch = Orchestrator()
        orch.register("a", lambda t: None)
        result = orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        self.assertEqual(result.status, "success")

    def test_dispatch_increments_stats_on_error(self):
        orch = Orchestrator()
        orch.dispatch(AgentTask(agent_name="no_such", prompt="p"))
        stats = orch.get_stats()
        self.assertEqual(stats["total_errors"], 1)
        self.assertEqual(stats["total_dispatched"], 1)

    def test_dispatch_chaining_register(self):
        orch = Orchestrator()
        result = orch.register("a", lambda t: "ok").register("b", lambda t: "ok2")
        self.assertIs(result, orch)


class TestOrchestratorCollectTaskId(unittest.TestCase):
    def test_collect_by_task_id_returns_one(self):
        orch = Orchestrator()
        orch.register("a", lambda t: "ok")
        task = AgentTask(agent_name="a", prompt="p", task_id="tid_42")
        orch.dispatch(task)
        results = orch.collect(task_id="tid_42")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_id, "tid_42")

    def test_collect_nonexistent_task_id_returns_empty(self):
        orch = Orchestrator()
        orch.register("a", lambda t: "ok")
        orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        results = orch.collect(task_id="does_not_exist_999")
        self.assertEqual(results, [])

    def test_collect_multiple_filters_together(self):
        orch = Orchestrator()
        def ok(task):
            return "ok"
        def fail(task):
            raise RuntimeError("err")
        orch.register("agent1", ok)
        orch.register("agent2", fail)
        t1 = AgentTask(agent_name="agent1", prompt="p", task_id="t1")
        t2 = AgentTask(agent_name="agent2", prompt="p", task_id="t2")
        orch.dispatch(t1)
        orch.dispatch(t2)
        # filter by agent_name AND status
        results = orch.collect(agent_name="agent1", status="success")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].agent_name, "agent1")


class TestOrchestratorStats(unittest.TestCase):
    def test_stats_start_at_zero(self):
        orch = Orchestrator()
        s = orch.get_stats()
        self.assertEqual(s["total_dispatched"], 0)
        self.assertEqual(s["total_success"], 0)
        self.assertEqual(s["total_errors"], 0)
        self.assertEqual(s["total_timeouts"], 0)

    def test_stats_total_success_increments(self):
        orch = Orchestrator()
        orch.register("a", lambda t: "ok")
        orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        s = orch.get_stats()
        self.assertEqual(s["total_success"], 1)

    def test_stats_are_independent_per_orchestrator(self):
        orch1 = Orchestrator()
        orch2 = Orchestrator()
        orch1.register("a", lambda t: "ok")
        orch1.dispatch(AgentTask(agent_name="a", prompt="p"))
        s2 = orch2.get_stats()
        self.assertEqual(s2["total_dispatched"], 0)


class TestOrchestratorShutdown(unittest.TestCase):
    def test_shutdown_returns_error_for_new_dispatches(self):
        orch = Orchestrator()
        orch.shutdown()
        result = orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        self.assertEqual(result.status, "error")
        self.assertIn("shutting down", result.error)

    def test_unregister_busy_agent_returns_false(self):
        orch = Orchestrator()
        def slow(task):
            time.sleep(0.1)
            return "done"
        orch.register("a", slow)
        t = AgentTask(agent_name="a", prompt="p", timeout=5)
        def do_dispatch():
            orch.dispatch(t)
        th = threading.Thread(target=do_dispatch)
        th.start()
        time.sleep(0.02)
        self.assertFalse(orch.unregister("a"))
        th.join()


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. orchestrator extended v2 - Iteration 57")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestOrchestratorDispatchEdgeCases,
        TestOrchestratorCollectTaskId,
        TestOrchestratorStats,
        TestOrchestratorShutdown,
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
