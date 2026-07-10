"""Extended tests v2 for plugin_sdk.py - Iteration 58 (fixed)"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.plugin_sdk import (
    PluginLoader,
    PluginManager,
    PluginManifest,
    XiaoYiPluginAPI,
)


class TestValidateManifest(unittest.TestCase):
    def test_empty_name_raises(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="", version="1.0", description="d", author="a", entry_point="m")
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_empty_version_raises(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="", description="d", author="a", entry_point="m")
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_empty_entry_point_raises(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a", entry_point="")
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_dangerous_perm_fs_write_raises(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", permissions=["fs_write"])
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_dangerous_perm_child_process_raises(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", permissions=["child_process"])
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_safe_permissions_pass(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", permissions=["llm_access", "event_bus"])
        loader._validate_manifest(m)  # no raise


class TestCreateSandbox(unittest.TestCase):
    def test_native_runtime_config(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", runtime="native")
        config = loader._create_sandbox(m)
        self.assertEqual(config["runtime"], "native")
        self.assertEqual(config["timeout"], 30)

    def test_python_uv_adds_venv_paths(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", runtime="python_uv", plugin_id="pid1")
        config = loader._create_sandbox(m)
        self.assertIn("venv_path", config)
        self.assertIn("python_path", config)

    def test_node_worker_adds_worker_type(self):
        loader = PluginLoader(plugins_dir=tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", runtime="node_worker")
        config = loader._create_sandbox(m)
        self.assertEqual(config["worker_type"], "isolated")


class TestPluginManagerSingleton(unittest.TestCase):
    def setUp(self):
        PluginManager._instance = None

    def tearDown(self):
        PluginManager._instance = None

    def test_same_instance_returned(self):
        m1 = PluginManager()
        m2 = PluginManager()
        self.assertIs(m1, m2)

    def test_different_dirs_second_call_keeps_first(self):
        m1 = PluginManager(plugins_dir="/tmp/test_pm_a")
        m2 = PluginManager(plugins_dir="/tmp/test_pm_b")
        self.assertIs(m1, m2)


class TestPluginManagerCrashRecovery(unittest.TestCase):
    def test_enable_failure_increments_crash_count(self):
        PluginManager._instance = None
        mgr = PluginManager(plugins_dir=tempfile.mkdtemp())
        result = mgr.enable("nonexistent_pid_999")
        self.assertFalse(result)
        self.assertEqual(mgr._crash_count.get("nonexistent_pid_999", 0), 1)
        PluginManager._instance = None


class TestXiaoYiPluginAPIReadFile(unittest.TestCase):
    def test_read_file_with_permission(self):
        api = XiaoYiPluginAPI("p1", ["file_read"])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello plugin")
            fname = f.name
        try:
            content = api.read_file(fname)
            self.assertIn("hello plugin", content)
        finally:
            import os as _os
            _os.remove(fname)


class TestPluginLoaderLoadError(unittest.TestCase):
    def test_load_plugin_missing_entry_point_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / "p_err"
            plugin_dir.mkdir()
            m = PluginManifest(name="p_err", version="1.0", description="d", author="a",
                                  entry_point="")
            loader = PluginLoader(plugins_dir=tmp)
            with self.assertRaises(ValueError):
                loader.load_plugin(m)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. plugin_sdk extended v2 - Iteration 58 (fixed)")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestValidateManifest,
        TestCreateSandbox,
        TestPluginManagerSingleton,
        TestPluginManagerCrashRecovery,
        TestXiaoYiPluginAPIReadFile,
        TestPluginLoaderLoadError,
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
