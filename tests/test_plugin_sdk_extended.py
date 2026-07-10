"""Extended tests for plugin_sdk.py - Iteration 48"""
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.plugin_sdk import (
    PluginInstance,
    PluginLoader,
    PluginManifest,
    PluginStatus,
    RuntimeType,
    XiaoYiPluginAPI,
)


class TestPluginManifest(unittest.TestCase):
    def test_minimal_manifest(self):
        m = PluginManifest(name="p", version="1.0",
                            description="d", author="a")
        self.assertIsNotNone(m.plugin_id)
        self.assertEqual(len(m.plugin_id), 8)

    def test_default_denied_apis(self):
        m = PluginManifest(name="p", version="1.0",
                            description="d", author="a")
        self.assertIn("fs", m.denied_apis)
        self.assertIn("child_process", m.denied_apis)

    def test_default_sandbox_true(self):
        m = PluginManifest(name="p", version="1.0",
                            description="d", author="a")
        self.assertTrue(m.sandbox)

    def test_custom_permissions(self):
        m = PluginManifest(name="p", version="1.0",
                            description="d", author="a",
                            permissions=["llm_access"])
        self.assertEqual(m.permissions, ["llm_access"])

    def test_unique_plugin_ids(self):
        m1 = PluginManifest(name="p", version="1.0",
                             description="d", author="a")
        m2 = PluginManifest(name="p", version="1.0",
                             description="d", author="a")
        self.assertNotEqual(m1.plugin_id, m2.plugin_id)


class TestPluginInstance(unittest.TestCase):
    def test_defaults(self):
        m = PluginManifest(name="p", version="1.0",
                            description="d", author="a")
        inst = PluginInstance(manifest=m, status=PluginStatus.LOADED)
        self.assertIsNone(inst.module)
        self.assertEqual(inst.error_message, "")
        self.assertEqual(inst.activation_count, 0)


class TestXiaoYiPluginAPI(unittest.TestCase):
    def test_check_permission_granted(self):
        api = XiaoYiPluginAPI("p1", ["llm_access"])
        self.assertTrue(api.check_permission("llm_access"))

    def test_check_permission_denied(self):
        api = XiaoYiPluginAPI("p1", [])
        self.assertFalse(api.check_permission("llm_access"))

    def test_log_access_records_entry(self):
        api = XiaoYiPluginAPI("p1", ["llm_access"])
        api.log_access("call_llm", {"model": "gpt"})
        self.assertEqual(api._audit_log[0]["api"], "call_llm")

    def test_log_access_truncates_long_args(self):
        api = XiaoYiPluginAPI("p1", ["llm_access"])
        api.log_access("call_llm", {"p": "x" * 500})
        self.assertLessEqual(len(api._audit_log[-1]["args"]), 200)

    def test_get_audit_log_returns_entries(self):
        api = XiaoYiPluginAPI("p1", ["llm_access"])
        api.log_access("a", {})
        api.log_access("b", {})
        self.assertEqual(len(api.get_audit_log()), 2)

    def test_get_config_no_permission_raises(self):
        api = XiaoYiPluginAPI("p1", [])
        with self.assertRaises(PermissionError):
            api.get_config("key")

    def test_read_file_no_permission_raises(self):
        api = XiaoYiPluginAPI("p1", [])
        with self.assertRaises(PermissionError):
            api.read_file("/etc/passwd")

    def test_emit_event_no_permission_raises(self):
        api = XiaoYiPluginAPI("p1", [])
        with self.assertRaises(PermissionError):
            api.emit_event("test", None)

    def test_call_llm_no_permission_raises(self):
        api = XiaoYiPluginAPI("p1", [])
        with self.assertRaises(PermissionError):
            api.call_llm("prompt")

    def test_get_system_stats_no_permission_raises(self):
        api = XiaoYiPluginAPI("p1", [])
        with self.assertRaises(PermissionError):
            api.get_system_stats()


class TestPluginLoader(unittest.TestCase):
    def _make_loader(self):
        return PluginLoader(plugins_dir=tempfile.mkdtemp())

    def test_discover_empty_dir(self):
        loader = self._make_loader()
        self.assertEqual(loader.discover_plugins(), [])

    def test_discover_plugin_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / "test_plugin"
            plugin_dir.mkdir()
            manifest_data = {
                "name": "test",
                "version": "1.0",
                "description": "test plugin",
                "author": "tester",
                "permissions": [],
                "runtime": "native",
            }
            (plugin_dir / "manifest.json").write_text(
                json.dumps(manifest_data), encoding="utf-8")
            loader = PluginLoader(plugins_dir=tmp)
            found = loader.discover_plugins()
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].name, "test")

    def test_load_plugin_returns_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / "p"
            plugin_dir.mkdir()
            m = PluginManifest(name="p", version="1.0",
                              description="d", author="a",
                              entry_point="main")
            manifest_data = asdict(m)
            (plugin_dir / "manifest.json").write_text(
                json.dumps(manifest_data), encoding="utf-8")
            loader = PluginLoader(plugins_dir=tmp)
            inst = loader.load_plugin(m)
            self.assertEqual(inst.status, PluginStatus.LOADED)
            self.assertEqual(inst.manifest.name, "p")


class TestPluginStatusEnum(unittest.TestCase):
    def test_all_statuses_defined(self):
        for s in ["loaded", "enabled", "disabled",
                   "error", "unloaded"]:
            self.assertIn(s, [e.value for e in PluginStatus])


class TestRuntimeTypeEnum(unittest.TestCase):
    def test_all_runtimes_defined(self):
        for r in ["python_uv", "python_venv",
                   "node_worker", "native"]:
            self.assertIn(r, [e.value for e in RuntimeType])


def run_all_tests():
    print("============================================================")
    print("J.A.R.V.I.S. plugin_sdk extended tests - Iteration 48")
    print("============================================================")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestPluginManifest, TestPluginInstance,
               TestXiaoYiPluginAPI, TestPluginLoader,
               TestPluginStatusEnum, TestRuntimeTypeEnum]:
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
