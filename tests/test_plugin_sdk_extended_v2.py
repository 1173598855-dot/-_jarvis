"""Extended tests v2 for plugin_sdk.py - Iteration 58 (fixed)"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.event_bus import EventBus
from core.kernel.plugin_broker import PluginBroker
from core.kernel.plugin_sdk import (
    PluginLoader,
    PluginManager,
    PluginManifest,
    XiaoYiPluginAPI,
)


def _loader(plugins_dir):
    return PluginLoader(plugins_dir, PluginBroker(EventBus(), grants={}))


class TestValidateManifest(unittest.TestCase):
    def test_empty_name_raises(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="", version="1.0", description="d", author="a", entry_point="m")
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_empty_version_raises(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="", description="d", author="a", entry_point="m")
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_empty_entry_point_raises(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a", entry_point="")
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_dangerous_perm_fs_write_raises(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", permissions=["fs_write"])
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_dangerous_perm_child_process_raises(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", permissions=["child_process"])
        with self.assertRaises(ValueError):
            loader._validate_manifest(m)

    def test_safe_permissions_pass(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", permissions=["llm_access", "event_bus"])
        loader._validate_manifest(m)  # no raise


class TestCreateSandbox(unittest.TestCase):
    def test_native_runtime_config(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", runtime="native")
        config = loader._create_sandbox(m)
        self.assertEqual(config["runtime"], "native")
        self.assertEqual(config["timeout"], 30)

    def test_python_uv_adds_venv_paths(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", runtime="python_uv", plugin_id="pid1")
        config = loader._create_sandbox(m)
        self.assertIn("venv_path", config)
        self.assertIn("python_path", config)

    def test_node_worker_adds_worker_type(self):
        loader = _loader(tempfile.mkdtemp())
        m = PluginManifest(name="p", version="1.0", description="d", author="a",
                              entry_point="m", runtime="node_worker")
        config = loader._create_sandbox(m)
        self.assertEqual(config["worker_type"], "isolated")


class TestPluginManagerSingleton(unittest.TestCase):
    def test_managers_are_independent_service_owners(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            m1 = PluginManager(first, event_bus=EventBus(), grants={})
            m2 = PluginManager(second, event_bus=EventBus(), grants={})
            self.addCleanup(m1.close)
            self.addCleanup(m2.close)
            self.assertIsNot(m1, m2)
            self.assertNotEqual(m1.loader.plugins_dir, m2.loader.plugins_dir)


class TestPluginManagerCrashRecovery(unittest.TestCase):
    def test_enable_failure_increments_crash_count(self):
        mgr = PluginManager(plugins_dir=tempfile.mkdtemp())
        self.addCleanup(mgr.close)
        result = mgr.enable("nonexistent_pid_999")
        self.assertFalse(result)
        self.assertEqual(mgr._crash_count.get("nonexistent_pid_999", 0), 1)


class TestXiaoYiPluginAPIReadFile(unittest.TestCase):
    def test_read_file_never_opens_files_without_a_broker(self):
        api = XiaoYiPluginAPI("p1", ["file_read"])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello plugin")
            fname = f.name
        try:
            with self.assertRaisesRegex(PermissionError, "PLUGIN_BROKER_DENIED"):
                api.read_file(fname)
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
            loader = _loader(tmp)
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
