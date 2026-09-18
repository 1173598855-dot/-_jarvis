"""Extended tests v2 for role_registry.py - Iteration 56 (API-corrected)"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.role_registry import AgentProfile, RoleRegistry

ROOT = Path(__file__).parent.parent
ROLE_REGISTRY_SCRIPT = ROOT / "src" / "core" / "brain" / "role_registry.py"


class TestRoleRegistryCLI(unittest.TestCase):
    def _run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(ROLE_REGISTRY_SCRIPT), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_get_command_prints_resolved_role(self):
        result = self._run_cli("get", "engineer")

        self.assertEqual(result.returncode, 0, result.stderr)
        profile = json.loads(result.stdout)
        self.assertEqual(profile["name"], "engineer")
        self.assertIn("coding", profile["capabilities"])

    def test_register_command_accepts_profile_file(self):
        profile = {
            "name": "cli_fixture",
            "display_name": "CLI Fixture",
            "description": "CLI registration fixture",
        }
        with tempfile.TemporaryDirectory(
            prefix=".test-role-registry-cli-",
            dir=ROOT,
        ) as temp_dir:
            profile_path = Path(temp_dir) / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            result = self._run_cli("register", str(profile_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Registered role: cli_fixture")


class TestRoleRegistrySnapshotOwnership(unittest.TestCase):
    def test_registry_detaches_mutable_profiles_and_snapshots(self):
        profile = AgentProfile(
            name="mutable",
            display_name="Mutable",
            description="d",
            capabilities=["original"],
            tools=["tool"],
            metadata={"nested": {"value": 1}},
        )
        reg = RoleRegistry()
        reg.register(profile)

        profile.capabilities.append("external")
        profile.metadata["nested"]["value"] = 2
        stored = reg.get("mutable")
        self.assertEqual(stored.capabilities, ["original"])
        self.assertEqual(stored.metadata, {"nested": {"value": 1}})

        stored.capabilities.append("caller")
        stored.metadata["nested"]["value"] = 3
        listed = reg.list_roles()
        listed[0].tools.append("caller")

        current = reg.get("mutable")
        self.assertEqual(current.capabilities, ["original"])
        self.assertEqual(current.tools, ["tool"])
        self.assertEqual(current.metadata, {"nested": {"value": 1}})

        inherited = RoleRegistry()
        inherited.register(
            AgentProfile(
                name="parent",
                display_name="Parent",
                description="d",
                metadata={"nested": {"parent": 1}},
            )
        )
        inherited.register(
            AgentProfile(
                name="child",
                display_name="Child",
                description="d",
                parent_role="parent",
                metadata={"child": {"value": 1}},
            )
        )
        resolved = inherited.get("child")
        resolved.metadata["nested"]["parent"] = 9
        resolved.metadata["child"]["value"] = 9
        self.assertEqual(
            inherited.get("child").metadata,
            {"nested": {"parent": 1}, "child": {"value": 1}},
        )


class TestRoleRegistryInheritanceCycles(unittest.TestCase):
    def test_register_rejects_direct_self_cycle_without_mutating_registry(self):
        registry = RoleRegistry()

        with self.assertRaisesRegex(
            ValueError,
            r"^Role inheritance cycle detected: self -> self$",
        ):
            registry.register(
                AgentProfile(
                    name="self",
                    display_name="Self",
                    description="d",
                    parent_role="self",
                )
            )

        self.assertEqual(len(registry), 0)

    def test_register_rejects_indirect_cycle_and_preserves_forward_reference(self):
        registry = RoleRegistry()
        registry.register(
            AgentProfile(
                name="child",
                display_name="Child",
                description="d",
                parent_role="future_parent",
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            r"^Role inheritance cycle detected: future_parent -> child -> future_parent$",
        ):
            registry.register(
                AgentProfile(
                    name="future_parent",
                    display_name="Future Parent",
                    description="d",
                    parent_role="child",
                )
            )

        self.assertIn("child", registry)
        self.assertNotIn("future_parent", registry)
        self.assertEqual(registry.get("child").parent_role, "future_parent")


class TestRoleRegistryDeepInheritance(unittest.TestCase):
    def test_get_resolves_chain_beyond_python_recursion_limit(self):
        registry = RoleRegistry()

        for index in range(1100):
            registry.register(
                AgentProfile(
                    name=f"role-{index}",
                    display_name=f"Role {index}",
                    description="deep inheritance fixture",
                    parent_role=f"role-{index - 1}" if index else None,
                    capabilities=[f"cap-{index}"],
                    priority=97 if index == 1099 else 1,
                )
            )

        resolved = registry.get("role-1099")

        self.assertIsNotNone(resolved)
        self.assertIsNone(resolved.parent_role)
        self.assertIn("cap-0", resolved.capabilities)
        self.assertIn("cap-1099", resolved.capabilities)
        self.assertEqual(resolved.priority, 97)


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
        TestRoleRegistryInheritanceCycles,
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
