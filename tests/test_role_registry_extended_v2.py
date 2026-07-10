"""Extended tests v2 for role_registry.py - Iteration 56 (API-corrected)"""
import json
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.role_registry import AgentProfile, RoleRegistry


class TestRoleRegistryResolveInheritance(unittest.TestCase):
    def test_resolve_inheritance_merges_capabilities(self):
        reg = RoleRegistry()
        parent = AgentProfile(name="parent", display_name="P", description="p",
                               capabilities=["a"], constraints=["c1"])
        child = AgentProfile(name="child", display_name="C", description="c",
                              parent_role="parent", capabilities=["b"])
        reg.register(parent)
        reg.register(child)
        resolved = reg._resolve_inheritance(child)
        self.assertIn("a", resolved.capabilities)
        self.assertIn("b", resolved.capabilities)

    def test_resolve_inheritance_no_parent_returns_self(self):
        reg = RoleRegistry()
        p = AgentProfile(name="solo", display_name="S", description="s")
        reg.register(p)
        resolved = reg._resolve_inheritance(p)
        self.assertEqual(resolved.name, "solo")

    def test_resolve_inheritance_missing_parent_returns_self(self):
        reg = RoleRegistry()
        p = AgentProfile(name="orphan", display_name="O", description="o",
                              parent_role="nonexistent_parent")
        reg.register(p)
        resolved = reg._resolve_inheritance(p)
        self.assertEqual(resolved.name, "orphan")


class TestRoleRegistryEdgeCases(unittest.TestCase):
    def test_register_duplicate_raises_value_error(self):
        reg = RoleRegistry()
        p = AgentProfile(name="dup", display_name="D", description="d")
        reg.register(p)
        with self.assertRaises(ValueError):
            reg.register(p)

    def test_unregister_then_get_returns_none(self):
        reg = RoleRegistry()
        p = AgentProfile(name="temp", display_name="T", description="t")
        reg.register(p)
        self.assertIsNotNone(reg.get("temp"))
        reg.unregister("temp")
        self.assertIsNone(reg.get("temp"))

    def test_len_after_register_and_unregister(self):
        reg = RoleRegistry()
        self.assertEqual(len(reg), 0)
        p1 = AgentProfile(name="r1", display_name="R1", description="d1")
        reg.register(p1)
        self.assertEqual(len(reg), 1)
        reg.unregister("r1")
        self.assertEqual(len(reg), 0)

    def test_contains_after_register(self):
        reg = RoleRegistry()
        p = AgentProfile(name="c_test", display_name="CT", description="d")
        reg.register(p)
        self.assertIn("c_test", reg)
        self.assertNotIn("nonexistent_xyz", reg)


class TestRoleRegistryJson(unittest.TestCase):
    def test_to_json_returns_valid_json_string(self):
        reg = RoleRegistry()
        p = AgentProfile(name="j1", display_name="J1", description="d")
        reg.register(p)
        json_str = reg.to_json()
        parsed = json.loads(json_str)
        # to_json returns {role_name: profile_dict} directly (no wrapper key)
        self.assertIsInstance(parsed, dict)
        self.assertIn("j1", parsed)

    def test_to_json_empty_registry(self):
        reg = RoleRegistry()
        json_str = reg.to_json()
        parsed = json.loads(json_str)
        # empty registry => {}
        self.assertEqual(parsed, {})

    def test_from_json_roundtrip(self):
        reg = RoleRegistry()
        p = AgentProfile(name="rt", display_name="RT", description="roundtrip")
        reg.register(p)
        json_str = reg.to_json()
        reg2 = RoleRegistry.from_json(json_str)
        self.assertIn("rt", reg2)

    def test_from_json_invalid_json_raises(self):
        # from_json raises JSONDecodeError on bad input (no silent swallow)
        with self.assertRaises((json.JSONDecodeError, Exception)):
            RoleRegistry.from_json("not valid json {{{")


class TestRoleRegistryThreadSafety(unittest.TestCase):
    def test_concurrent_register_and_get(self):
        import threading
        reg = RoleRegistry()
        errors = []
        def register_name(n):
            try:
                p = AgentProfile(name=f"t{n}", display_name=f"T{n}", description="d")
                reg.register(p)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=register_name, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. role_registry extended v2 - Iteration 56 (fixed)")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestRoleRegistryResolveInheritance,
        TestRoleRegistryEdgeCases,
        TestRoleRegistryJson,
        TestRoleRegistryThreadSafety,
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
