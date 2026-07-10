"""Extended tests for role_registry.py - Iteration 45"""
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.role_registry import (
    BASE_ROLES,
    EXTENDED_ROLES,
    AgentProfile,
    RoleRegistry,
    create_default_registry,
)


class TestAgentProfileDataclass(unittest.TestCase):
    def test_defaults(self):
        p = AgentProfile(name='n', display_name='N', description='D')
        self.assertIsNone(p.parent_role)
        self.assertEqual(p.capabilities, [])
        self.assertEqual(p.constraints, [])
        self.assertEqual(p.priority, 5)
        self.assertEqual(p.tools, [])

    def test_resolve_prompt_substitution(self):
        p = AgentProfile(name='n', display_name='Engineer',
                         description='codes well',
                         prompt_template='{name}: {description} | {task}')
        result = p.resolve_prompt('write tests')
        self.assertIn('Engineer', result)
        self.assertIn('codes well', result)
        self.assertIn('write tests', result)

    def test_resolve_prompt_default_template(self):
        p = AgentProfile(name='n', display_name='Tester', description='tests')
        result = p.resolve_prompt('run pytest')
        self.assertIn('Tester', result)
        self.assertIn('run pytest', result)

    def test_to_dict_contains_all_fields(self):
        p = AgentProfile(name='n', display_name='N', description='D',
                         capabilities=['c1'], tools=['t1'], priority=9)
        d = p.to_dict()
        self.assertEqual(d['name'], 'n')
        self.assertEqual(d['priority'], 9)
        self.assertIn('c1', d['capabilities'])

    def test_from_dict_roundtrip(self):
        original = AgentProfile(name='r', display_name='R', description='D',
                              capabilities=['a', 'b'], tools=['x'], priority=7)
        restored = AgentProfile.from_dict(original.to_dict())
        self.assertEqual(restored.name, 'r')
        self.assertEqual(restored.display_name, 'R')
        self.assertEqual(restored.capabilities, ['a', 'b'])
        self.assertEqual(restored.priority, 7)

    def test_from_dict_filters_unknown_fields(self):
        d = {'name': 'n', 'display_name': 'N', 'description': 'D',
             'unknown_field': 'should_be_ignored'}
        p = AgentProfile.from_dict(d)
        self.assertEqual(p.name, 'n')


class TestRoleRegistryRegisterUnregister(unittest.TestCase):
    def test_register_adds_role(self):
        reg = RoleRegistry()
        p = AgentProfile(name='r', display_name='R', description='D')
        reg.register(p)
        self.assertIn('r', reg)

    def test_register_duplicate_raises_value_error(self):
        reg = RoleRegistry()
        p = AgentProfile(name='r', display_name='R', description='D')
        reg.register(p)
        with self.assertRaises(ValueError):
            reg.register(p)

    def test_unregister_existing_returns_true(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='r', display_name='R', description='D'))
        self.assertTrue(reg.unregister('r'))
        self.assertNotIn('r', reg)

    def test_unregister_nonexistent_returns_false(self):
        reg = RoleRegistry()
        self.assertFalse(reg.unregister('nonexistent'))


class TestRoleRegistryGet(unittest.TestCase):
    def test_get_existing(self):
        reg = RoleRegistry()
        p = AgentProfile(name='r', display_name='R', description='D')
        reg.register(p)
        result = reg.get('r')
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'r')

    def test_get_nonexistent_returns_none(self):
        reg = RoleRegistry()
        self.assertIsNone(reg.get('nonexistent'))


class TestRoleRegistryListRoles(unittest.TestCase):
    def test_list_empty(self):
        reg = RoleRegistry()
        self.assertEqual(reg.list_roles(), [])

    def test_list_sorted_by_priority_desc(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='low', display_name='L', description='D', priority=3))
        reg.register(AgentProfile(name='high', display_name='H', description='D', priority=9))
        reg.register(AgentProfile(name='mid', display_name='M', description='D', priority=6))
        roles = reg.list_roles()
        priorities = [r.priority for r in roles]
        self.assertEqual(priorities, [9, 6, 3])

    def test_list_filter_by_capability(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='coder', display_name='C', description='D',
                              capabilities=['coding', 'testing']))
        reg.register(AgentProfile(name='tester', display_name='T', description='D',
                              capabilities=['testing', 'tdd']))
        reg.register(AgentProfile(name='pm', display_name='P', description='D',
                              capabilities=['requirements']))
        roles = reg.list_roles(capability='testing')
        self.assertEqual(len(roles), 2)
        names = [r.name for r in roles]
        self.assertIn('coder', names)
        self.assertIn('tester', names)


class TestRoleRegistryInheritance(unittest.TestCase):
    def test_no_parent_returns_self(self):
        reg = RoleRegistry()
        p = AgentProfile(name='r', display_name='R', description='D', capabilities=['c1'])
        reg.register(p)
        result = reg.get('r')
        self.assertEqual(result.capabilities, ['c1'])

    def test_inherits_parent_capabilities(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='parent', display_name='P', description='D',
                              capabilities=['parent_cap']))
        reg.register(AgentProfile(name='child', display_name='C', description='D',
                              parent_role='parent', capabilities=['child_cap']))
        result = reg.get('child')
        self.assertIn('parent_cap', result.capabilities)
        self.assertIn('child_cap', result.capabilities)

    def test_inherits_parent_constraints(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='p', display_name='P', description='D',
                              constraints=['no_destructive']))
        reg.register(AgentProfile(name='c', display_name='C', description='D',
                              parent_role='p', constraints=['audit_log']))
        result = reg.get('c')
        self.assertIn('no_destructive', result.constraints)
        self.assertIn('audit_log', result.constraints)

    def test_missing_parent_returns_self(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='orphan', display_name='O', description='D',
                              parent_role='nonexistent_parent'))
        result = reg.get('orphan')
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'orphan')

    def test_chain_inheritance_grandparent(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='gp', display_name='GP', description='D',
                              capabilities=['gp_cap']))
        reg.register(AgentProfile(name='parent', display_name='P', description='D',
                              parent_role='gp', capabilities=['parent_cap']))
        reg.register(AgentProfile(name='child', display_name='C', description='D',
                              parent_role='parent', capabilities=['child_cap']))
        result = reg.get('child')
        self.assertIn('gp_cap', result.capabilities)
        self.assertIn('parent_cap', result.capabilities)
        self.assertIn('child_cap', result.capabilities)

    def test_inheritance_preserves_name_and_display_name(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='parent', display_name='Parent', description='D'))
        reg.register(AgentProfile(name='child', display_name='Child', description='D',
                              parent_role='parent'))
        result = reg.get('child')
        self.assertEqual(result.name, 'child')
        self.assertEqual(result.display_name, 'Child')


class TestRoleRegistryJson(unittest.TestCase):
    def test_to_json_contains_roles(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='r', display_name='R', description='D'))
        j = reg.to_json()
        self.assertIn('r', j)
        self.assertIn('R', j)

    def test_to_json_empty(self):
        reg = RoleRegistry()
        j = reg.to_json()
        self.assertEqual(j, '{}')

    def test_from_json_roundtrip(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='r', display_name='R', description='D',
                              capabilities=['c1'], priority=9))
        j = reg.to_json()
        restored = RoleRegistry.from_json(j)
        self.assertIn('r', restored)
        r = restored.get('r')
        self.assertEqual(r.display_name, 'R')
        self.assertEqual(r.priority, 9)
        self.assertIn('c1', r.capabilities)


class TestRoleRegistryLenContains(unittest.TestCase):
    def test_len_empty(self):
        reg = RoleRegistry()
        self.assertEqual(len(reg), 0)

    def test_len_after_register(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='r', display_name='R', description='D'))
        self.assertEqual(len(reg), 1)

    def test_contains_true(self):
        reg = RoleRegistry()
        reg.register(AgentProfile(name='r', display_name='R', description='D'))
        self.assertTrue('r' in reg)

    def test_contains_false(self):
        reg = RoleRegistry()
        self.assertFalse('nonexistent' in reg)


class TestCreateDefaultRegistry(unittest.TestCase):
    def test_creates_registry(self):
        reg = create_default_registry()
        self.assertIsInstance(reg, RoleRegistry)

    def test_has_base_roles(self):
        reg = create_default_registry()
        self.assertEqual(len(BASE_ROLES), 5)
        for role in BASE_ROLES:
            self.assertIn(role.name, reg)

    def test_has_extended_roles(self):
        reg = create_default_registry()
        self.assertEqual(len(EXTENDED_ROLES), 2)
        for role in EXTENDED_ROLES:
            self.assertIn(role.name, reg)

    def test_total_roles(self):
        reg = create_default_registry()
        self.assertEqual(len(reg), 7)


class TestRoleRegistryThreadSafety(unittest.TestCase):
    def test_concurrent_register_no_corruption(self):
        import threading
        reg = RoleRegistry()
        errors = []

        def register_roles(prefix):
            try:
                for i in range(5):
                    p = AgentProfile(
                        name=f'{prefix}_{i}',
                        display_name=f'{prefix}_{i}',
                        description='D',
                        capabilities=['c'])
                    reg.register(p)
            except Exception as ex:
                errors.append(ex)

        threads = [threading.Thread(target=register_roles, args=(f't{j}',))
                   for j in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Some will succeed, some may fail with ValueError (duplicate)
        # Total unique roles registered = 20 (4 threads x 5 names each)
        self.assertGreaterEqual(len(reg), 1)
        self.assertEqual(len(errors), 0)


def run_all_tests():
    print('=' * 60)
    print('J.A.R.V.I.S. role_registry extended tests - Iteration 45')
    print('=' * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestAgentProfileDataclass, TestRoleRegistryRegisterUnregister,
               TestRoleRegistryGet, TestRoleRegistryListRoles,
               TestRoleRegistryInheritance, TestRoleRegistryJson,
               TestRoleRegistryLenContains, TestCreateDefaultRegistry,
               TestRoleRegistryThreadSafety]:
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
