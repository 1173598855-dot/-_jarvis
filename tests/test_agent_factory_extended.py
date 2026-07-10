"""Extended tests for agent_factory.py - Iteration 47"""
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.agent_factory import AgentFactory, DispatchResult
from core.brain.orchestrator import AgentTask, Orchestrator
from core.brain.role_registry import AgentProfile, RoleRegistry


class TestDispatchResult(unittest.TestCase):
    def test_defaults(self):
        r = DispatchResult("r", "t1", "ok")
        self.assertEqual(r.role_name, "r")
        self.assertEqual(r.task_id, "t1")
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.message, "")

    def test_to_dict(self):
        r = DispatchResult("r", "t1", "ok", message="m")
        d = r.to_dict()
        self.assertEqual(d["role_name"], "r")
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["message"], "m")


class TestAgentFactoryInit(unittest.TestCase):
    def test_default_creates_registry_and_orchestrator(self):
        f = AgentFactory()
        self.assertIsNotNone(f.registry)
        self.assertIsNotNone(f.orchestrator)

    def test_custom_registry(self):
        reg = RoleRegistry()
        f = AgentFactory(registry=reg)
        self.assertIs(f.registry, reg)

    def test_custom_orchestrator(self):
        orch = Orchestrator()
        f = AgentFactory(orchestrator=orch)
        self.assertIs(f.orchestrator, orch)

    def test_none_registry_creates_default(self):
        f = AgentFactory(registry=None)
        self.assertIsNotNone(f.registry)
        self.assertEqual(len(f.registry), 7)  # 5 base + 2 extended


class TestAgentFactoryDispatchByRole(unittest.TestCase):
    def test_dispatch_nonexistent_role(self):
        f = AgentFactory()
        r = f.dispatch_by_role("nonexistent_role", "task")
        self.assertEqual(r.status, "no_role")

    def test_dispatch_existing_role(self):
        f = AgentFactory()
        r = f.dispatch_by_role("engineer", "write tests")
        self.assertEqual(r.role_name, "engineer")
        self.assertIsNotNone(r.task_id)

    def test_dispatch_auto_registers_agent(self):
        f = AgentFactory()
        f.dispatch_by_role("engineer", "task")
        self.assertIn("engineer", f.orchestrator._agents)

    def test_dispatch_result_contains_display_name(self):
        f = AgentFactory()
        r = f.dispatch_by_role("engineer", "task")
        self.assertIn("工程师", r.message)


class TestAgentFactoryDispatchByCapability(unittest.TestCase):
    def test_dispatch_nonexistent_capability(self):
        f = AgentFactory()
        r = f.dispatch_by_capability("nonexistent_cap_xyz", "task")
        self.assertEqual(r.status, "no_capability")

    def test_dispatch_existing_capability(self):
        f = AgentFactory()
        r = f.dispatch_by_capability("coding", "task")
        self.assertIsNotNone(r.task_id)


class TestAgentFactoryBatchDispatch(unittest.TestCase):
    def test_batch_by_role(self):
        f = AgentFactory()
        tasks = [{"role": "engineer", "prompt": "t1"}]
        results = f.batch_dispatch(tasks)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].role_name, "engineer")

    def test_batch_by_capability(self):
        f = AgentFactory()
        tasks = [{"capability": "testing", "prompt": "t1"}]
        results = f.batch_dispatch(tasks)
        self.assertEqual(len(results), 1)

    def test_batch_missing_role_and_capability(self):
        f = AgentFactory()
        tasks = [{"prompt": "t1"}]
        results = f.batch_dispatch(tasks)
        # Empty role/capability should still dispatch (empty role -> no_role or no_capability)
        self.assertEqual(len(results), 1)

    def test_batch_multiple_tasks(self):
        f = AgentFactory()
        tasks = [
            {"role": "engineer", "prompt": "t1"},
            {"role": "tester", "prompt": "t2"},
        ]
        results = f.batch_dispatch(tasks)
        self.assertEqual(len(results), 2)


class TestAgentFactoryListRoles(unittest.TestCase):
    def test_list_roles(self):
        f = AgentFactory()
        roles = f.list_roles()
        self.assertEqual(len(roles), 7)

    def test_list_roles_filter_capability(self):
        f = AgentFactory()
        roles = f.list_roles(capability="coding")
        self.assertGreater(len(roles), 0)
        for r in roles:
            self.assertIn("coding", r.capabilities)


class TestAgentFactoryGetRole(unittest.TestCase):
    def test_get_existing_role(self):
        f = AgentFactory()
        r = f.get_role("engineer")
        self.assertIsNotNone(r)
        self.assertEqual(r.name, "engineer")

    def test_get_nonexistent_role(self):
        f = AgentFactory()
        r = f.get_role("nonexistent_role_xyz")
        self.assertIsNone(r)


class TestAgentFactoryDefaultHandler(unittest.TestCase):
    def test_handler_returns_display_name(self):
        f = AgentFactory()
        profile = AgentProfile(name="e", display_name="工程师",
                              description="codes")
        handler = f._default_handler(profile)
        task = AgentTask(agent_name="e", prompt="write code")
        result = handler(task)
        self.assertIn("工程师", result)

    def test_handler_truncates_long_prompt(self):
        f = AgentFactory()
        profile = AgentProfile(name="e", display_name="E",
                              description="d")
        handler = f._default_handler(profile)
        long_prompt = "x" * 200
        task = AgentTask(agent_name="e", prompt=long_prompt)
        result = handler(task)
        self.assertLessEqual(len(result), 200)


class TestAgentFactoryBuildFullPrompt(unittest.TestCase):
    def test_prompt_contains_role_display_name(self):
        f = AgentFactory()
        profile = AgentProfile(name="e", display_name="工程师",
                              description="codes well")
        full = f._build_full_prompt(profile, "task", "system")
        self.assertIn("工程师", full)

    def test_prompt_starts_with_role_tag(self):
        f = AgentFactory()
        profile = AgentProfile(name="e", display_name="E",
                              description="d")
        full = f._build_full_prompt(profile, "t", "s")
        self.assertTrue(full.startswith("[ROLE: E]"))


def run_all_tests():
    print("============================================================")
    print("J.A.R.V.I.S. agent_factory extended tests - Iteration 47")
    print("============================================================")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestDispatchResult, TestAgentFactoryInit,
        TestAgentFactoryDispatchByRole, TestAgentFactoryDispatchByCapability,
        TestAgentFactoryBatchDispatch,
        TestAgentFactoryListRoles, TestAgentFactoryGetRole,
        TestAgentFactoryDefaultHandler, TestAgentFactoryBuildFullPrompt,
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
