"""Extended tests for orchestrator.py - Iteration 43"""
import sys
import time
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.orchestrator import (
    AgentInfo,
    AgentResult,
    AgentStatus,
    AgentTask,
    Orchestrator,
    _RegisteredAgent,
)


class TestAgentTaskDataclass(unittest.TestCase):
    def test_default_task_id_generated(self):
        t = AgentTask(agent_name='a', prompt='p')
        self.assertNotEqual(t.task_id, '')

    def test_generated_task_id_length(self):
        t = AgentTask(agent_name='a', prompt='p')
        self.assertEqual(len(t.task_id), 8)

    def test_explicit_task_id_preserved(self):
        t = AgentTask(task_id='custom_id', agent_name='a', prompt='p')
        self.assertEqual(t.task_id, 'custom_id')

    def test_defaults(self):
        t = AgentTask(agent_name='a', prompt='p')
        self.assertEqual(t.timeout, 30)
        self.assertEqual(t.priority, 1)
        self.assertEqual(t.metadata, {})

    def test_custom_fields(self):
        t = AgentTask(agent_name='a', prompt='p', timeout=60, priority=3, metadata={'k': 'v'})
        self.assertEqual(t.timeout, 60)
        self.assertEqual(t.priority, 3)
        self.assertEqual(t.metadata['k'], 'v')


class TestAgentResultSerialization(unittest.TestCase):
    def test_to_dict_all_fields(self):
        r = AgentResult(task_id='t1', agent_name='a', result='ok',
                       error='', duration_ms=100, status='success')
        d = r.to_dict()
        self.assertEqual(d['task_id'], 't1')
        self.assertEqual(d['status'], 'success')

    def test_to_dict_empty_error(self):
        r = AgentResult(task_id='t1', agent_name='a')
        d = r.to_dict()
        self.assertEqual(d['error'], '')

    def test_to_dict_default_status(self):
        r = AgentResult(task_id='t1', agent_name='a')
        self.assertEqual(r.status, 'unknown')


class TestAgentInfoDataclass(unittest.TestCase):
    def test_defaults(self):
        info = AgentInfo(name='agent1')
        self.assertEqual(info.name, 'agent1')
        self.assertEqual(info.capabilities, [])
        self.assertEqual(info.tasks_completed, 0)
        self.assertEqual(info.errors_count, 0)
        self.assertEqual(info.status, AgentStatus.IDLE.value)

    def test_with_capabilities(self):
        info = AgentInfo(name='a', capabilities=['x', 'y'], tasks_completed=5)
        self.assertEqual(info.capabilities, ['x', 'y'])


class TestRegisteredAgentLifecycle(unittest.TestCase):
    def _make_agent(self, name='test_agent', handler=None):
        if handler is None:
            def handler(task):
                return 'done'
        return _RegisteredAgent(name, handler, ['cap1'])

    def test_initial_status_idle(self):
        a = self._make_agent()
        self.assertTrue(a.is_available())

    def test_assign_changes_status(self):
        a = self._make_agent()
        task = AgentTask(agent_name='test_agent', prompt='p')
        a.assign(task)
        self.assertFalse(a.is_available())
        self.assertEqual(a.status, AgentStatus.BUSY)

    def test_complete_returns_to_idle(self):
        a = self._make_agent()
        task = AgentTask(agent_name='test_agent', prompt='p')
        a.assign(task)
        a.complete()
        self.assertTrue(a.is_available())

    def test_fail_sets_error_status(self):
        a = self._make_agent()
        a.assign(AgentTask(agent_name='test_agent', prompt='p'))
        a.fail()
        self.assertEqual(a.status, AgentStatus.ERROR)

    def test_info_returns_agent_info(self):
        a = self._make_agent('my_agent', ['c1', 'c2'])
        info = a.info()
        self.assertIsInstance(info, AgentInfo)
        self.assertEqual(info.name, 'my_agent')

    def test_info_capabilities_is_list(self):
        a = self._make_agent('a')
        info = a.info()
        self.assertIsInstance(info.capabilities, list)
        self.assertEqual(info.capabilities, ['cap1'])  # default from _make_agent
    def test_complete_clears_current_task(self):
        a = self._make_agent()
        task = AgentTask(agent_name='test_agent', prompt='p')
        a.assign(task)
        self.assertIsNotNone(a.current_task)
        a.complete()
        self.assertIsNone(a.current_task)


class TestOrchestratorInitAndShutdown(unittest.TestCase):
    def test_default_init(self):
        orch = Orchestrator()
        self.assertEqual(orch._default_timeout, 30)
        self.assertFalse(orch._shutdown)

    def test_custom_timeout(self):
        orch = Orchestrator(default_timeout=60)
        self.assertEqual(orch._default_timeout, 60)

    def test_shutdown_blocks_new_dispatches(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        orch.shutdown()
        result = orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        self.assertEqual(result.status, 'error')

    def test_shutdown_sets_flag(self):
        orch = Orchestrator()
        orch.shutdown()
        self.assertTrue(orch._shutdown)

    def test_shutdown_empty_orchestrator(self):
        orch = Orchestrator()
        orch.shutdown()
        self.assertTrue(orch._shutdown)


class TestOrchestratorRegisterUnregister(unittest.TestCase):
    def test_register_returns_self(self):
        orch = Orchestrator()
        result = orch.register('a', lambda t: 'ok')
        self.assertIs(result, orch)

    def test_register_adds_agent(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok', capabilities=['c1'])
        self.assertIn('a', orch._agents)

    def test_register_replaces_existing(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'first')
        orch.register('a', lambda t: 'second')
        result = orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        self.assertEqual(result.result, 'second')

    def test_unregister_nonexistent_returns_false(self):
        orch = Orchestrator()
        self.assertFalse(orch.unregister('nonexistent'))

    def test_unregister_success(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        self.assertTrue(orch.unregister('a'))
        self.assertNotIn('a', orch._agents)

    def test_list_agents_empty(self):
        orch = Orchestrator()
        self.assertEqual(orch.list_agents(), [])

    def test_list_agents_populated(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok', capabilities=['c1'])
        agents = orch.list_agents()
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].name, 'a')


class TestOrchestratorDispatch(unittest.TestCase):
    def test_dispatch_unknown_agent(self):
        orch = Orchestrator()
        result = orch.dispatch(AgentTask(agent_name='missing', prompt='p'))
        self.assertEqual(result.status, 'error')

    def test_dispatch_increments_total_dispatched(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        self.assertEqual(orch._stats['total_dispatched'], 1)

    def test_dispatch_increments_total_success(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        self.assertEqual(orch._stats['total_success'], 1)

    def test_dispatch_handler_raises_exception(self):
        orch = Orchestrator()
        def handler(task):
            raise ValueError('test error')
        orch.register('a', handler)
        result = orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        self.assertEqual(result.status, 'error')
        self.assertEqual(orch._stats['total_errors'], 1)

    def test_dispatch_timeout(self):
        orch = Orchestrator(default_timeout=1)
        def slow(task):
            time.sleep(5)
            return 'never'
        orch.register('slow', slow)
        result = orch.dispatch(AgentTask(agent_name='slow', prompt='p', timeout=1))
        self.assertEqual(result.status, 'timeout')

    def test_dispatch_records_history(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        self.assertEqual(len(orch._history), 1)


class TestOrchestratorDispatchConcurrent(unittest.TestCase):
    def test_concurrent_multiple_agents(self):
        orch = Orchestrator()
        for i in range(3):
            orch.register(f'agent{i}', lambda t, i=i: {'id': i})
        tasks = [AgentTask(agent_name=f'agent{i}', prompt='p') for i in range(3)]
        results = orch.dispatch_concurrent(tasks)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.status == 'success' for r in results))

    def test_concurrent_empty_list(self):
        orch = Orchestrator()
        self.assertEqual(orch.dispatch_concurrent([]), [])

    def test_same_agent_concurrent_busy_result(self):
        orch = Orchestrator()
        def handler(task):
            time.sleep(0.05)
            return 'done'
        orch.register('a', handler)
        tasks = [AgentTask(agent_name='a', prompt='p') for _ in range(3)]
        results = orch.dispatch_concurrent(tasks)
        self.assertEqual(len(results), 3)
        statuses = [r.status for r in results]
        self.assertIn('success', statuses)


class TestOrchestratorCollect(unittest.TestCase):
    def _populate(self, orch, n=3):
        for i in range(n):
            orch.register(f'a{i}', lambda t, i=i: f'r{i}')
            orch.dispatch(AgentTask(agent_name=f'a{i}', prompt='p'))

    def test_collect_empty(self):
        orch = Orchestrator()
        self.assertEqual(orch.collect(), [])

    def test_collect_all(self):
        orch = Orchestrator()
        self._populate(orch, 3)
        self.assertEqual(len(orch.collect()), 3)

    def test_collect_filter_by_agent_name(self):
        orch = Orchestrator()
        orch.register('target', lambda t: 'ok')
        orch.register('other', lambda t: 'ok')
        orch.dispatch(AgentTask(agent_name='target', prompt='p'))
        orch.dispatch(AgentTask(agent_name='other', prompt='p'))
        results = orch.collect(agent_name='target')
        self.assertEqual(len(results), 1)

    def test_collect_filter_by_status(self):
        orch = Orchestrator()
        def fail(task):
            raise RuntimeError('fail')
        orch.register('ok', lambda t: 'ok')
        orch.register('fail', fail)
        orch.dispatch(AgentTask(agent_name='ok', prompt='p'))
        orch.dispatch(AgentTask(agent_name='fail', prompt='p'))
        results = orch.collect(status='error')
        self.assertEqual(len(results), 1)

    def test_collect_limit(self):
        orch = Orchestrator()
        self._populate(orch, 10)
        results = orch.collect(limit=3)
        self.assertEqual(len(results), 3)


class TestOrchestratorRunWithTimeout(unittest.TestCase):
    def test_timeout_fires(self):
        orch = Orchestrator()
        def slow(task):
            time.sleep(10)
        with self.assertRaises(TimeoutError):
            orch._run_with_timeout(slow, AgentTask(agent_name='a', prompt='p'), 1)

    def test_normal_completion(self):
        orch = Orchestrator()
        result = orch._run_with_timeout(lambda t: 42, AgentTask(agent_name='a', prompt='p'), 30)
        self.assertEqual(result, 42)

    def test_handler_exception_propagates(self):
        orch = Orchestrator()
        def failing(task):
            raise RuntimeError('handler error')
        with self.assertRaises(RuntimeError):
            orch._run_with_timeout(failing, AgentTask(agent_name='a', prompt='p'), 30)


class TestOrchestratorEdgeCases(unittest.TestCase):
    def test_get_stats_returns_copy(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        s1 = orch.get_stats()
        s1['total_dispatched'] = 999
        s2 = orch.get_stats()
        self.assertEqual(s2['total_dispatched'], 1)

    def test_stats_after_multiple_dispatches(self):
        orch = Orchestrator()
        orch.register('ok', lambda t: 'ok')
        def fail(task):
            raise RuntimeError()
        orch.register('fail', fail)
        orch.dispatch(AgentTask(agent_name='ok', prompt='p'))
        orch.dispatch(AgentTask(agent_name='ok', prompt='p'))
        orch.dispatch(AgentTask(agent_name='fail', prompt='p'))
        stats = orch.get_stats()
        self.assertEqual(stats['total_dispatched'], 3)
        self.assertEqual(stats['total_success'], 2)
        self.assertEqual(stats['total_errors'], 1)

    def test_collect_after_shutdown(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        orch.shutdown()
        results = orch.collect()
        self.assertEqual(len(results), 1)

    def test_dispatch_after_shutdown_returns_error(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        orch.shutdown()
        result = orch.dispatch(AgentTask(agent_name='a', prompt='p'))
        self.assertEqual(result.status, 'error')

    def test_concurrent_no_stats_corruption(self):
        orch = Orchestrator()
        orch.register('a', lambda t: 'ok')
        tasks = [AgentTask(agent_name='a', prompt='p') for _ in range(20)]
        results = orch.dispatch_concurrent(tasks)
        self.assertEqual(len(results), 20)
        self.assertEqual(orch.get_stats()['total_dispatched'], 20)


def run_all_tests():
    print('=' * 60)
    print('J.A.R.V.I.S. orchestrator extended tests - Iteration 43')
    print('=' * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestAgentTaskDataclass, TestAgentResultSerialization,
               TestAgentInfoDataclass, TestRegisteredAgentLifecycle,
               TestOrchestratorInitAndShutdown, TestOrchestratorRegisterUnregister,
               TestOrchestratorDispatch, TestOrchestratorDispatchConcurrent,
               TestOrchestratorCollect, TestOrchestratorRunWithTimeout,
               TestOrchestratorEdgeCases]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print()
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f'Results: {total} tests, {passed} passed, {len(result.failures)} failed, {len(result.errors)} errors')
    print('=' * 60)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
