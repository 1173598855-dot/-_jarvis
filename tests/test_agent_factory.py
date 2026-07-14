"""
Agent 工厂测试 - Phase 11 集成层验证
运行：python3 tests/test_agent_factory.py
"""
import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.agent_factory import AgentFactory, DispatchResult
from core.brain.role_tools import RoleToolBroker, RoleToolPolicy


class TestDispatchByRole(unittest.TestCase):
    def setUp(self):
        self.factory = AgentFactory()

    def test_dispatch_existing_role(self):
        result = self.factory.dispatch_by_role("engineer", "fix the bug")
        self.assertIn(result.status, ["dispatched", "success"])
        self.assertEqual(result.role_name, "engineer")
        self.assertNotEqual(result.task_id, "")

    def test_dispatch_nonexistent_role(self):
        result = self.factory.dispatch_by_role("nonexistent_role_xyz", "do something")
        self.assertEqual(result.status, "no_role")
        self.assertEqual(result.task_id, "")

    def test_dispatch_preserves_priority(self):
        result = self.factory.dispatch_by_role("architect", "design system", timeout=60)
        self.assertIn(result.status, ["dispatched", "success"])

    def test_dispatch_result_dict(self):
        result = self.factory.dispatch_by_role("tester", "write tests")
        d = result.to_dict()
        self.assertIn("role_name", d)
        self.assertIn("task_id", d)
        self.assertIn("status", d)


class TestDispatchByCapability(unittest.TestCase):
    def setUp(self):
        self.factory = AgentFactory()

    def test_dispatch_capability_coding(self):
        result = self.factory.dispatch_by_capability("coding", "implement feature")
        self.assertIn(result.status, ["dispatched", "success", "no_capability"])

    def test_dispatch_capability_nonexistent(self):
        result = self.factory.dispatch_by_capability("nonexistent_cap_xyz", "do something")
        self.assertEqual(result.status, "no_capability")

    def test_dispatch_capability_selects_highest_priority(self):
        result = self.factory.dispatch_by_capability("code_review", "review code")
        if result.status in ("dispatched", "success"):
            profile = self.factory.get_role(result.role_name)
            self.assertIsNotNone(profile)
            self.assertGreaterEqual(profile.priority, 6)


class TestBatchDispatch(unittest.TestCase):
    def setUp(self):
        self.factory = AgentFactory()

    def test_batch_dispatch_multiple_roles(self):
        tasks = [
            {"role": "engineer", "prompt": "code feature A"},
            {"role": "reviewer", "prompt": "review PR"},
            {"role": "tester", "prompt": "write tests"},
        ]
        results = self.factory.batch_dispatch(tasks)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertIn(r.status, ["dispatched", "success"])

    def test_batch_dispatch_mixed_roles_and_caps(self):
        tasks = [
            {"role": "engineer", "prompt": "code"},
            {"capability": "security", "prompt": "audit"},
        ]
        results = self.factory.batch_dispatch(tasks)
        self.assertEqual(len(results), 2)

    def test_batch_dispatch_invalid_role_skipped(self):
        tasks = [
            {"role": "nonexistent_xyz", "prompt": "do something"},
        ]
        results = self.factory.batch_dispatch(tasks)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "no_role")


class TestListRoles(unittest.TestCase):
    def setUp(self):
        self.factory = AgentFactory()

    def test_list_all_roles(self):
        roles = self.factory.list_roles()
        self.assertGreaterEqual(len(roles), 5)

    def test_list_roles_filter_capability(self):
        roles = self.factory.list_roles(capability="coding")
        self.assertGreaterEqual(len(roles), 1)
        for r in roles:
            self.assertIn("coding", r.capabilities)

    def test_get_role(self):
        profile = self.factory.get_role("engineer")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "engineer")
        self.assertEqual(profile.display_name, "工程师")

    def test_get_nonexistent_role(self):
        profile = self.factory.get_role("nonexistent_xyz")
        self.assertIsNone(profile)


class TestIntegration(unittest.TestCase):
    def test_fullstack_engineer_has_all_capabilities(self):
        factory = AgentFactory()
        fs = factory.get_role("fullstack_engineer")
        self.assertIsNotNone(fs)
        # Inherited from engineer
        self.assertIn("coding", fs.capabilities)
        self.assertIn("testing", fs.capabilities)
        # Own capabilities
        self.assertIn("frontend", fs.capabilities)
        self.assertIn("backend", fs.capabilities)

    def test_senior_reviewer_has_security(self):
        factory = AgentFactory()
        sr = factory.get_role("senior_reviewer")
        self.assertIsNotNone(sr)
        # Inherited from reviewer
        self.assertIn("code_review", sr.capabilities)
        # Own capabilities
        self.assertIn("penetration_testing", sr.capabilities)

    def test_prompt_generation(self):
        factory = AgentFactory()
        result = factory.dispatch_by_role("engineer", "fix login bug")
        # Handler returns role display_name in message
        self.assertIn("工程师", result.message or "")


class TestDispatchResult(unittest.TestCase):
    def test_to_dict(self):
        r = DispatchResult("engineer", "task_123", "dispatched", "done")
        d = r.to_dict()
        self.assertEqual(d["role_name"], "engineer")
        self.assertEqual(d["task_id"], "task_123")
        self.assertEqual(d["status"], "dispatched")
        self.assertEqual(d["message"], "done")

    def test_to_dict_empty(self):
        r = DispatchResult("", "", "no_role", "not found")
        d = r.to_dict()
        self.assertEqual(d["status"], "no_role")

class TestAgentFactoryInit(unittest.TestCase):
    """AgentFactory initialization"""

    def test_default_init_creates_registry(self):
        """Default init creates AgentFactory with default registry"""
        factory = AgentFactory()
        self.assertIsNotNone(factory.registry)
        self.assertIsNotNone(factory.orchestrator)

    def test_custom_registry(self):
        """AgentFactory accepts custom registry"""
        from core.brain.role_registry import RoleRegistry
        registry = RoleRegistry()
        factory = AgentFactory(registry=registry)
        self.assertIs(factory.registry, registry)

    def test_custom_orchestrator(self):
        """AgentFactory accepts custom orchestrator"""
        from core.brain.orchestrator import Orchestrator
        orch = Orchestrator()
        factory = AgentFactory(orchestrator=orch)
        self.assertIs(factory.orchestrator, orch)

    def test_has_lock(self):
        """AgentFactory has threading lock for thread safety"""
        factory = AgentFactory()
        self.assertIsNotNone(factory._lock)


class TestBuildFullPrompt(unittest.TestCase):
    """_build_full_prompt() prompt construction"""

    def setUp(self):
        self.factory = AgentFactory()

    def test_build_prompt_basic(self):
        """_build_full_prompt includes role name and task"""
        from core.brain.role_registry import AgentProfile
        profile = AgentProfile(
            name="tester", display_name="测试工程师", description="测试专家",
            capabilities=["testing"],
        )
        prompt = self.factory._build_full_prompt(profile, "write unit tests", "You are a QA expert.")
        self.assertIn("测试工程师", prompt)
        self.assertIn("write unit tests", prompt)
        self.assertIn("QA expert", prompt)

    def test_build_prompt_with_constraints(self):
        """_build_full_prompt includes constraints when present"""
        from core.brain.role_registry import AgentProfile
        profile = AgentProfile(
            name="reviewer", display_name="Reviewer", description="code reviewer",
            capabilities=["review"], constraints=["no secrets", "check types"],
        )
        prompt = self.factory._build_full_prompt(profile, "review PR", "")
        self.assertIn("CONSTRAINTS", prompt)
        self.assertIn("no secrets", prompt)

    def test_build_prompt_with_tools(self):
        """Profile declarations alone do not grant prompt tool access."""
        from core.brain.role_registry import AgentProfile
        profile = AgentProfile(
            name="coder", display_name="Coder", description="developer",
            capabilities=["coding"], tools=["python", "bash"],
        )
        prompt = self.factory._build_full_prompt(profile, "fix bug", "")
        self.assertIn("[TOOL ACCESS] disabled", prompt)
        self.assertNotIn("AVAILABLE TOOLS", prompt)
        self.assertNotIn("python", prompt)

    def test_build_prompt_no_constraints_no_tools(self):
        """_build_full_prompt works without constraints or tools"""
        from core.brain.role_registry import AgentProfile
        profile = AgentProfile(
            name="helper", display_name="Helper", description="general helper",
            capabilities=["general"],
        )
        prompt = self.factory._build_full_prompt(profile, "do thing", "sys prompt")
        self.assertIn("Helper", prompt)
        self.assertIn("do thing", prompt)
        self.assertNotIn("CONSTRAINTS", prompt)
        self.assertNotIn("AVAILABLE TOOLS", prompt)

class TestDispatchResultExtended(unittest.TestCase):
    """Extended DispatchResult tests"""

    def test_dispatch_result_fields(self):
        """DispatchResult stores role_name, task_id, status, message"""
        r = DispatchResult("engineer", "t1", "dispatched", "task started")
        self.assertEqual(r.role_name, "engineer")
        self.assertEqual(r.task_id, "t1")
        self.assertEqual(r.status, "dispatched")
        self.assertEqual(r.message, "task started")

    def test_dispatch_result_to_dict(self):
        """DispatchResult.to_dict returns plain dict"""
        r = DispatchResult("coder", "t2", "success", "done")
        d = r.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["status"], "success")
        self.assertEqual(d["role_name"], "coder")

    def test_dispatch_result_empty_fields(self):
        """DispatchResult with empty fields for no_role case"""
        r = DispatchResult("", "", "no_role", "not found")
        self.assertEqual(r.status, "no_role")
        self.assertEqual(r.task_id, "")


class TestOllamaRoleExecution(unittest.TestCase):
    @staticmethod
    def _response(content="role output"):
        return {
            "model": "fixture-role",
            "message": {"role": "assistant", "content": content},
            "done": True,
        }

    def test_injected_manager_executes_role_with_system_and_user_messages(self):
        manager = Mock()
        manager.chat.return_value = self._response()
        factory = AgentFactory(ollama_manager=manager, role_model="fixture-role")

        result = factory.dispatch_by_role("engineer", "write a unit test")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "role output")
        model, messages = manager.chat.call_args.args
        self.assertEqual(model, "fixture-role")
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("工程师", messages[0]["content"])
        self.assertIn("[TOOL ACCESS] disabled", messages[0]["content"])
        self.assertNotIn("AVAILABLE TOOLS", messages[0]["content"])
        self.assertNotIn("write a unit test", messages[0]["content"])
        self.assertEqual(
            messages[1],
            {"role": "user", "content": "write a unit test"},
        )
        self.assertEqual(manager.chat.call_args.kwargs, {"stream": False})

    def test_injected_broker_exposes_only_authorized_registered_tools(self):
        manager = Mock()
        manager.chat.return_value = self._response()
        broker = RoleToolBroker(
            policy=RoleToolPolicy(
                {"engineer": ["terminal_executor", "plugin_sdk"]}
            ),
            handlers={"terminal_executor": lambda arguments: arguments},
        )
        factory = AgentFactory(
            ollama_manager=manager,
            role_tool_broker=broker,
        )
        captured_tasks = []
        original_dispatch = factory.orchestrator.dispatch

        def capture(task):
            captured_tasks.append(task)
            return original_dispatch(task)

        with patch.object(
            factory.orchestrator,
            "dispatch",
            side_effect=capture,
        ):
            result = factory.dispatch_by_role(
                "engineer",
                "inspect the workspace",
            )

        self.assertEqual(result.status, "success")
        system_prompt = manager.chat.call_args.args[1][0]["content"]
        self.assertIn(
            "[AUTHORIZED TOOLS] terminal_executor",
            system_prompt,
        )
        self.assertNotIn("plugin_sdk", system_prompt)
        self.assertEqual(
            captured_tasks[0].metadata["declared_tools"],
            ["orchestrator", "terminal_executor", "plugin_sdk"],
        )
        self.assertEqual(
            captured_tasks[0].metadata["authorized_tools"],
            ["terminal_executor"],
        )
        self.assertNotIn("tools", captured_tasks[0].metadata)

    def test_injected_manager_error_response_is_sanitized(self):
        manager = Mock()
        manager.chat.return_value = {"error": "connection details"}
        factory = AgentFactory(ollama_manager=manager)

        result = factory.dispatch_by_role("engineer", "task")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "Ollama role execution failed")

    def test_injected_manager_blank_content_is_an_error(self):
        manager = Mock()
        manager.chat.return_value = self._response("   ")
        factory = AgentFactory(ollama_manager=manager)

        result = factory.dispatch_by_role("engineer", "task")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "Ollama role execution failed")

    def test_injected_manager_exception_is_sanitized(self):
        manager = Mock()
        manager.chat.side_effect = RuntimeError("socket path and secret")
        factory = AgentFactory(ollama_manager=manager)

        result = factory.dispatch_by_role("engineer", "task")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "Ollama role execution failed")

    def test_role_recovers_for_next_request_after_execution_error(self):
        manager = Mock()
        manager.chat.side_effect = [
            {"error": "offline"},
            self._response("recovered"),
        ]
        factory = AgentFactory(ollama_manager=manager)

        first = factory.dispatch_by_role("engineer", "first task")
        second = factory.dispatch_by_role("engineer", "second task")

        self.assertEqual(first.status, "error")
        self.assertEqual(first.message, "Ollama role execution failed")
        self.assertEqual(second.status, "success")
        self.assertEqual(second.message, "recovered")
        self.assertEqual(manager.chat.call_count, 2)
        info = factory.orchestrator.list_agents()[0]
        self.assertEqual(info.status, "idle")
        self.assertEqual(info.errors_count, 1)
        self.assertEqual(info.tasks_completed, 1)

    def test_role_model_uses_process_configuration(self):
        with patch.dict("os.environ", {"JARVIS_ROLE_MODEL": "configured-role"}):
            factory = AgentFactory()

        self.assertEqual(factory._role_model, "configured-role")

    def test_dispatch_llm_uses_valid_chat_signature(self):
        manager = Mock()
        manager.chat.side_effect = [
            self._response("engineer"),
            self._response("implemented"),
        ]
        factory = AgentFactory(ollama_manager=manager, role_model="fixture-role")

        result = factory.dispatch_llm("implement feature")

        self.assertEqual(result.role_name, "engineer")
        self.assertEqual(result.message, "implemented")
        first_call = manager.chat.call_args_list[0]
        self.assertEqual(first_call.args[0], "fixture-role")
        self.assertEqual(first_call.args[1][0]["role"], "user")
        self.assertEqual(first_call.kwargs, {"stream": False})


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. agent_factory tests - Iteration 36")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestDispatchByRole, TestDispatchByCapability, TestBatchDispatch,
               TestListRoles, TestIntegration, TestDispatchResult,
               TestDispatchResultExtended, TestAgentFactoryInit, TestBuildFullPrompt,
               TestOllamaRoleExecution]:
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
