"""
角色注册表测试 - Phase 11 MetaGPT 集成层验证
运行：python3 tests/test_role_registry.py
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brain.role_registry import AgentProfile, RoleRegistry, create_default_registry


class TestRoleRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = RoleRegistry()

    def test_register_get(self):
        p = AgentProfile(name="t1", display_name="T1", description="d1")
        self.registry.register(p)
        result = self.registry.get("t1")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "t1")

    def test_register_duplicate_raises(self):
        p = AgentProfile(name="dup", display_name="D", description="d")
        self.registry.register(p)
        with self.assertRaises(ValueError):
            self.registry.register(p)

    def test_unregister(self):
        p = AgentProfile(name="del", display_name="D", description="d")
        self.registry.register(p)
        self.assertTrue(self.registry.unregister("del"))
        self.assertIsNone(self.registry.get("del"))
        self.assertFalse(self.registry.unregister("del"))

    def test_contains(self):
        p = AgentProfile(name="x", display_name="X", description="d")
        self.assertFalse("x" in self.registry)
        self.registry.register(p)
        self.assertTrue("x" in self.registry)

    def test_list_roles(self):
        self.registry.register(AgentProfile(name="a", display_name="A", description="d", capabilities=["coding"]))
        self.registry.register(AgentProfile(name="b", display_name="B", description="d", capabilities=["review"]))
        roles = self.registry.list_roles()
        self.assertEqual(len(roles), 2)

    def test_list_roles_filter_capability(self):
        self.registry.register(AgentProfile(name="a", display_name="A", description="d", capabilities=["coding"]))
        self.registry.register(AgentProfile(name="b", display_name="B", description="d", capabilities=["review"]))
        roles = self.registry.list_roles(capability="coding")
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0].name, "a")

    def test_inheritance(self):
        parent = AgentProfile(
            name="base", display_name="Base", description="base",
            capabilities=["coding"], tools=["tool1"], constraints=["no_destructive"],
        )
        child = AgentProfile(
            name="derived", display_name="Derived", description="derived",
            parent_role="base", capabilities=["testing"],
            tools=["tool2"], constraints=["audit_log"],
        )
        self.registry.register(parent)
        self.registry.register(child)
        result = self.registry.get("derived")
        self.assertIn("coding", result.capabilities)
        self.assertIn("testing", result.capabilities)
        self.assertIn("tool1", result.tools)
        self.assertIn("tool2", result.tools)
        self.assertIn("no_destructive", result.constraints)
        self.assertIn("audit_log", result.constraints)

    def test_inheritance_missing_parent(self):
        child = AgentProfile(
            name="orphan", display_name="Orphan", description="d",
            parent_role="nonexistent", capabilities=["x"],
        )
        self.registry.register(child)
        result = self.registry.get("orphan")
        self.assertEqual(result.capabilities, ["x"])

    def test_inheritance_priority_max(self):
        parent = AgentProfile(name="p", display_name="P", description="d", priority=3)
        child = AgentProfile(name="c", display_name="C", description="d", parent_role="p", priority=8)
        self.registry.register(parent)
        self.registry.register(child)
        result = self.registry.get("c")
        self.assertEqual(result.priority, 8)

    def test_to_json_roundtrip(self):
        registry = create_default_registry()
        json_str = registry.to_json()
        restored = RoleRegistry.from_json(json_str)
        self.assertEqual(len(registry), len(restored))
        for name in registry._roles:
            self.assertIn(name, restored)

    def test_default_registry_has_roles(self):
        registry = create_default_registry()
        self.assertGreaterEqual(len(registry), 5)
        names = [r.name for r in registry.list_roles()]
        self.assertIn("engineer", names)
        self.assertIn("architect", names)

    def test_extended_roles_inherit(self):
        registry = create_default_registry()
        fs = registry.get("fullstack_engineer")
        self.assertIsNotNone(fs)
        self.assertIn("coding", fs.capabilities)
        self.assertIn("testing", fs.capabilities)
        self.assertIn("frontend", fs.capabilities)
        self.assertIn("backend", fs.capabilities)

    def test_thread_safety(self):
        import threading
        errors = []
        def add_many(prefix):
            try:
                for i in range(10):
                    p = AgentProfile(name=f"{prefix}_{i}", display_name=f"{prefix[0].upper()}{i}", description="d")
                    self.registry.register(p)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=add_many, args=(f"t{j}",)) for j in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)
        self.assertGreaterEqual(len(self.registry), 30)

    def test_priority_sorting(self):
        self.registry.register(AgentProfile(name="low", display_name="L", description="d", priority=1))
        self.registry.register(AgentProfile(name="high", display_name="H", description="d", priority=10))
        roles = self.registry.list_roles()
        self.assertEqual(roles[0].name, "high")
        self.assertEqual(roles[-1].name, "low")




# ============================================================
# Test: AgentProfile
# ============================================================

class TestAgentProfile(unittest.TestCase):

    def test_resolve_prompt_basic(self):
        """resolve_prompt fills template with name, description, task"""
        profile = AgentProfile(
            name="coder", display_name="工程师",
            description="精通Python",
            prompt_template="You are {name}. {description}\n\nTask: {task}",
        )
        result = profile.resolve_prompt("write a function")
        self.assertIn("工程师", result)
        self.assertIn("精通Python", result)
        self.assertIn("write a function", result)

    def test_resolve_prompt_default_template(self):
        """resolve_prompt uses default template when not specified"""
        profile = AgentProfile(
            name="pm", display_name="产品经理",
            description="负责需求",
        )
        result = profile.resolve_prompt("写PRD")
        self.assertIn("产品经理", result)
        self.assertIn("负责需求", result)
        self.assertIn("写PRD", result)

    def test_resolve_prompt_special_chars_in_task(self):
        """resolve_prompt handles special characters in task"""
        profile = AgentProfile(
            name="test", display_name="Test",
            description="Desc", prompt_template="Task: {task}",
        )
        result = profile.resolve_prompt("fix: O(N^2) bug")
        self.assertIn("fix: O(N^2) bug", result)

    def test_to_dict_includes_all_fields(self):
        """to_dict returns dict with all AgentProfile fields"""
        profile = AgentProfile(
            name="eng", display_name="工程师",
            description="coding", capabilities=["coding"],
            tools=["terminal"], priority=7, metadata={"key": "val"},
        )
        d = profile.to_dict()
        self.assertEqual(d["name"], "eng")
        self.assertEqual(d["display_name"], "工程师")
        self.assertEqual(d["priority"], 7)
        self.assertEqual(d["capabilities"], ["coding"])
        self.assertEqual(d["tools"], ["terminal"])
        self.assertEqual(d["metadata"], {"key": "val"})

    def test_from_dict_creates_profile(self):
        """from_dict reconstructs AgentProfile from dict"""
        d = {
            "name": "arch", "display_name": "架构师",
            "description": "system design", "parent_role": None,
            "capabilities": ["design"], "constraints": [],
            "prompt_template": "You are {name}", "tools": ["scanner"],
            "priority": 9, "metadata": {},
        }
        profile = AgentProfile.from_dict(d)
        self.assertEqual(profile.name, "arch")
        self.assertEqual(profile.display_name, "架构师")
        self.assertEqual(profile.priority, 9)
        self.assertEqual(profile.capabilities, ["design"])

    def test_from_dict_ignores_unknown_fields(self):
        """from_dict ignores extra keys not in dataclass fields"""
        d = {
            "name": "x", "display_name": "X",
            "description": "d", "unknown_field": "ignored",
            "capabilities": [], "constraints": [],
            "prompt_template": "t", "tools": [],
            "priority": 5, "metadata": {},
        }
        profile = AgentProfile.from_dict(d)
        self.assertEqual(profile.name, "x")
        self.assertFalse(hasattr(profile, "unknown_field"))


# ============================================================
# Test: RoleRegistry classmethods and factory
# ============================================================

class TestRoleRegistryClassMethods(unittest.TestCase):

    def test_from_json_creates_registry(self):
        """RoleRegistry.from_json reconstructs registry from JSON"""
        registry = create_default_registry()
        json_str = registry.to_json()
        restored = RoleRegistry.from_json(json_str)
        self.assertEqual(len(restored), len(registry))
        self.assertIn("engineer", restored)
        self.assertIn("architect", restored)

    def test_from_json_preserves_capabilities(self):
        """from_json preserves role capabilities"""
        registry = create_default_registry()
        json_str = registry.to_json()
        restored = RoleRegistry.from_json(json_str)
        eng = restored.get("engineer")
        self.assertIsNotNone(eng)
        self.assertIn("coding", eng.capabilities)
        self.assertIn("testing", eng.capabilities)

    def test_from_json_roundtrip_equality(self):
        """to_json -> from_json produces equivalent registry"""
        r1 = create_default_registry()
        json_str = r1.to_json()
        r2 = RoleRegistry.from_json(json_str)
        # Both should have same roles
        roles1 = sorted([p.name for p in r1.list_roles()])
        roles2 = sorted([p.name for p in r2.list_roles()])
        self.assertEqual(roles1, roles2)

    def test_from_json_empty_registry(self):
        """RoleRegistry.from_json handles empty registry JSON"""
        empty_json = json.dumps({}, ensure_ascii=False)
        registry = RoleRegistry.from_json(empty_json)
        self.assertEqual(len(registry), 0)

    def test_create_default_registry_has_base_roles(self):
        """create_default_registry includes all 5 base roles"""
        registry = create_default_registry()
        base_names = ["product_manager", "architect", "engineer", "reviewer", "tester"]
        for name in base_names:
            self.assertIn(name, registry, f"Base role '{name}' not found")

    def test_create_default_registry_has_extended_roles(self):
        """create_default_registry includes extended roles"""
        registry = create_default_registry()
        self.assertIn("fullstack_engineer", registry)
        self.assertIn("senior_reviewer", registry)

    def test_create_default_registry_total_count(self):
        """create_default_registry has 7 total roles"""
        registry = create_default_registry()
        self.assertEqual(len(registry), 7)

    def test_get_extended_role_inherits_parent_capabilities(self):
        """fullstack_engineer inherits engineer capabilities"""
        registry = create_default_registry()
        fs = registry.get("fullstack_engineer")
        self.assertIn("coding", fs.capabilities)
        self.assertIn("frontend", fs.capabilities)
        self.assertIn("backend", fs.capabilities)

    def test_get_extended_role_inherits_parent_tools(self):
        """fullstack_engineer inherits engineer tools"""
        registry = create_default_registry()
        fs = registry.get("fullstack_engineer")
        self.assertIn("terminal_executor", fs.tools)
        self.assertIn("ollama_manager", fs.tools)

    def test_agent_profile_default_template_format(self):
        """Default prompt_template uses {name}, {description}, {task}"""
        profile = AgentProfile(name="x", display_name="X", description="Y")
        self.assertIn("{name}", profile.prompt_template)
        self.assertIn("{description}", profile.prompt_template)
        self.assertIn("{task}", profile.prompt_template)



def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. role_registry tests - Iteration 22")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestAgentProfile, TestRoleRegistry]:
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
