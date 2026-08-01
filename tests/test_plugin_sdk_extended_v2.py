"""Extended tests v2 for plugin_sdk.py - Iteration 58 (fixed)"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.plugin_sdk import (
    PluginLoader,
    PluginManager,
    PluginManifest,
    XiaoYiPluginAPI,
)
from core.kernel.event_bus import EventBus
from core.contracts.plugin_worker_protocol import LifecycleAction, PluginLifecycleResult


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


class TestPluginManagerOwnership(unittest.TestCase):
    def setUp(self):
        PluginManager._instance = None

    def tearDown(self):
        PluginManager._instance = None

    def test_managers_are_per_service_owners(self):
        m1 = PluginManager()
        m2 = PluginManager()
        self.assertIsNot(m1, m2)

    def test_different_dirs_remain_independent(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            m1 = PluginManager(plugins_dir=first)
            m2 = PluginManager(plugins_dir=second)
            self.assertNotEqual(m1.loader.plugins_dir, m2.loader.plugins_dir)


class TestPluginManagerCrashRecovery(unittest.TestCase):
    def test_enable_failure_increments_crash_count(self):
        PluginManager._instance = None
        mgr = PluginManager(plugins_dir=tempfile.mkdtemp())
        result = mgr.enable("nonexistent_pid_999")
        self.assertFalse(result)
        self.assertEqual(mgr._crash_count.get("nonexistent_pid_999", 0), 1)
        PluginManager._instance = None


class TestXiaoYiPluginAPIReadFile(unittest.TestCase):
    def test_read_file_with_permission_still_requires_broker(self):
        api = XiaoYiPluginAPI("p1", ["file_read"])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello plugin")
            fname = f.name
        try:
            with self.assertRaises(RuntimeError):
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
            loader = PluginLoader(plugins_dir=tmp)
            with self.assertRaises(ValueError):
                loader.load_plugin(m)


class TestWorkerCoordinatorGuards(unittest.TestCase):
    def test_invalid_root_or_entrypoint_returns_bounded_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = PluginManifest(
                name="missing", version="1", description="", plugin_id="missing",
                runtime="python_worker", entry_point="../outside.py",
            )
            result = PluginLoader(tmp).load_plugin(manifest)
            self.assertEqual(result.status.value, "error")
            self.assertIn("PLUGIN_", result.error_message)

    def test_disable_is_successful_when_plugin_has_no_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "no-hook"
            root.mkdir()
            (root / "plugin.py").write_text("def activate(api): pass", encoding="utf-8")
            manifest = PluginManifest(
                name="no-hook", version="1", description="", plugin_id="no-hook",
                runtime="python_worker", entry_point="plugin.py",
            )
            manager = PluginManager(tmp, event_bus=EventBus())
            try:
                self.assertEqual(manager.load(manifest).status.value, "loaded")
                self.assertTrue(manager.disable("no-hook"))
                self.assertEqual(manager.get_plugin("no-hook").status.value, "disabled")
            finally:
                manager.close()

    def test_unload_missing_returns_false(self):
        manager = PluginManager(tempfile.mkdtemp(), event_bus=EventBus())
        try:
            self.assertFalse(manager.unload("missing"))
        finally:
            manager.close()

    def test_manager_close_attempts_every_worker_when_cleanup_fails(self):
        closed = []

        class Runtime:
            def __init__(self, root, spec, broker):
                self.name = Path(root).name
                self.snapshot = SimpleNamespace(
                    pid=100 + len(closed), generation=spec.generation,
                    termination_confirmed=False,
                )

            def start(self):
                return self.snapshot

            def invoke(self, action):
                if action is LifecycleAction.CLEANUP and self.name == "first":
                    raise RuntimeError("cleanup failed")
                status = {
                    LifecycleAction.LOAD: "loaded",
                    LifecycleAction.CLEANUP: "unloaded",
                }.get(action, "disabled")
                return PluginLifecycleResult(
                    request_id="request-1", plugin_id=self.name, success=True,
                    status=status, error="", audit=(),
                )

            def close(self):
                closed.append(self.name)
                self.snapshot.termination_confirmed = True

        with tempfile.TemporaryDirectory() as tmp:
            for plugin_id in ("first", "second"):
                root = Path(tmp) / plugin_id
                root.mkdir()
                (root / "plugin.py").write_text("", encoding="utf-8")
            manager = PluginManager(tmp, event_bus=EventBus(), runtime_factory=Runtime)
            try:
                for plugin_id in ("first", "second"):
                    manager.load(PluginManifest(
                        name=plugin_id, version="1", description="", plugin_id=plugin_id,
                        runtime="python_worker", entry_point="plugin.py",
                    ))
                manager.close()
                self.assertCountEqual(closed, ["first", "second"])
            finally:
                manager.close()

    def test_failed_load_with_unconfirmed_worker_stays_registered(self):
        runtimes = []
        actions = []

        class Runtime:
            def __init__(self, root, spec, broker):
                self.snapshot = SimpleNamespace(
                    pid=321,
                    generation=spec.generation,
                    termination_confirmed=False,
                )
                runtimes.append(self)

            def start(self):
                return self.snapshot

            def invoke(self, action):
                actions.append(action)
                return PluginLifecycleResult(
                    request_id="request-1",
                    plugin_id="stuck-load",
                    success=False,
                    status="error",
                    error="PLUGIN_LIFECYCLE_FAILED",
                    audit=(),
                )

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stuck-load"
            root.mkdir()
            (root / "plugin.py").write_text("", encoding="utf-8")
            manifest = PluginManifest(
                name="stuck-load",
                version="1",
                description="",
                plugin_id="stuck-load",
                runtime="python_worker",
                entry_point="plugin.py",
            )
            loader = PluginLoader(tmp, runtime_factory=Runtime)

            instance = loader.load_plugin(manifest)

            self.assertEqual(instance.status.value, "error")
            self.assertFalse(instance.termination_confirmed)
            self.assertIs(loader.get_plugin("stuck-load"), instance)
            self.assertFalse(loader.enable_plugin("stuck-load"))
            self.assertIs(loader.load_plugin(manifest), instance)
            self.assertEqual(len(runtimes), 1)
            self.assertEqual(actions, [LifecycleAction.LOAD])


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. plugin_sdk extended v2 - Iteration 58 (fixed)")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestValidateManifest,
        TestCreateSandbox,
        TestPluginManagerOwnership,
        TestPluginManagerCrashRecovery,
        TestXiaoYiPluginAPIReadFile,
        TestPluginLoaderLoadError,
        TestWorkerCoordinatorGuards,
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
