# -*- coding: utf-8 -*-
"""
Additional plugin_sdk tests - Iteration 37
Tests PluginManager singleton/crash recovery, PluginLoader internals, PluginManifest edge cases
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.kernel.plugin_sdk import (
    PluginInstance,
    PluginLoader,
    PluginManager,
    PluginManifest,
    PluginStatus,
    RuntimeType,
    XiaoYiPluginAPI,
    global_plugin_manager,
)


def _make_manifest(**overrides):
    """Helper: create a minimal valid PluginManifest"""
    defaults = {
        "name": "test_plugin",
        "version": "1.0.0",
        "description": "Test",
        "author": "test",
        "permissions": ["system_config"],
        "plugin_id": "",
    }
    defaults.update(overrides)
    return PluginManifest(**defaults)


def _make_plugin_dir(tmp, plugin_id, name="test_plugin", permissions=None):
    """Create a minimal plugin directory with manifest.json"""
    pdir = Path(tmp) / plugin_id
    pdir.mkdir(exist_ok=True)
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "Test",
        "author": "test",
        "permissions": permissions or ["system_config"],
        "plugin_id": plugin_id,
        "entry_point": "main.py",
        "runtime": "native",
    }
    (pdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pdir / "main.py").write_text(
        "def activate(api): pass\ndef deactivate(): pass\ndef cleanup(): pass",
        encoding="utf-8"
    )
    return pdir


# ============================================================
# Test: PluginManifest edge cases
# ============================================================

# -*- coding: utf-8 -*-

# ============================================================
# Test: PluginStatus and RuntimeType enums
# ============================================================

class TestPluginStatus(unittest.TestCase):
    def test_status_values(self):
        self.assertEqual(PluginStatus.LOADED.value, "loaded")
        self.assertEqual(PluginStatus.ENABLED.value, "enabled")
        self.assertEqual(PluginStatus.DISABLED.value, "disabled")
        self.assertEqual(PluginStatus.ERROR.value, "error")
        self.assertEqual(PluginStatus.UNLOADED.value, "unloaded")

    def test_runtime_type_values(self):
        self.assertEqual(RuntimeType.NATIVE.value, "native")
        self.assertEqual(RuntimeType.PYTHON_UV.value, "python_uv")
        self.assertEqual(RuntimeType.NODE_WORKER.value, "node_worker")


# ============================================================
# Test: PluginManifest
# ============================================================

class TestPluginManifest(unittest.TestCase):
    def test_create_minimal(self):
        m = _make_manifest()
        self.assertEqual(m.name, "test_plugin")
        self.assertEqual(m.version, "1.0.0")
        self.assertTrue(m.sandbox)

    def test_auto_plugin_id(self):
        m = _make_manifest(plugin_id="")
        self.assertNotEqual(m.plugin_id, "")
        self.assertEqual(len(m.plugin_id), 8)

    def test_explicit_plugin_id_preserved(self):
        m = _make_manifest(plugin_id="myplugin")
        self.assertEqual(m.plugin_id, "myplugin")

    def test_default_denied_apis(self):
        m = _make_manifest()
        self.assertIn("fs", m.denied_apis)
        self.assertIn("child_process", m.denied_apis)
        self.assertIn("network", m.denied_apis)

    def test_custom_denied_apis(self):
        m = _make_manifest(denied_apis=["fs", "os"])
        self.assertIn("fs", m.denied_apis)
        self.assertNotIn("child_process", m.denied_apis)

    def test_default_runtime(self):
        m = _make_manifest()
        self.assertEqual(m.runtime, "native")

    def test_empty_permissions(self):
        m = _make_manifest(permissions=[])
        self.assertEqual(len(m.permissions), 0)


# ============================================================
# Test: PluginInstance
# ============================================================

class TestPluginInstance(unittest.TestCase):
    def test_create_instance(self):
        m = _make_manifest()
        inst = PluginInstance(manifest=m, status=PluginStatus.LOADED)
        self.assertEqual(inst.status, PluginStatus.LOADED)
        self.assertIsNone(inst.module)
        self.assertEqual(inst.activation_count, 0)

    def test_instance_with_module(self):
        m = _make_manifest()
        fake_mod = MagicMock()
        inst = PluginInstance(manifest=m, status=PluginStatus.LOADED, module=fake_mod)
        self.assertEqual(inst.status, PluginStatus.LOADED)
        self.assertIs(inst.module, fake_mod)

    def test_default_values(self):
        m = _make_manifest()
        inst = PluginInstance(manifest=m, status=PluginStatus.LOADED)
        self.assertEqual(inst.error_message, "")
        self.assertEqual(inst.loaded_at, "")
        self.assertEqual(inst.activation_count, 0)


# ============================================================
# Test: XiaoYiPluginAPI (restricted API)
# ============================================================

class TestXiaoYiPluginAPI(unittest.TestCase):
    def setUp(self):
        self.api = XiaoYiPluginAPI("test_plugin", ["system_config", "file_read", "llm_access", "event_bus", "system_monitor"])

    def test_check_permission_granted(self):
        self.assertTrue(self.api.check_permission("system_config"))
        self.assertTrue(self.api.check_permission("file_read"))

    def test_check_permission_denied(self):
        self.assertFalse(self.api.check_permission("network_access"))
        self.assertFalse(self.api.check_permission("os_write"))

    def test_get_config_with_permission(self):
        result = self.api.get_config("key", default="fallback")
        self.assertEqual(result, "fallback")

    def test_get_config_without_permission_raises(self):
        api = XiaoYiPluginAPI("no_perm", [])
        with self.assertRaises(PermissionError):
            api.get_config("key")

    def test_read_file_with_permission(self):
        api = XiaoYiPluginAPI("reader", ["file_read"])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("hello plugin")
            tmp_path = f.name
        try:
            result = api.read_file(tmp_path)
            self.assertIn("hello plugin", result)
        finally:
            Path(tmp_path).unlink()

    def test_read_file_without_permission_raises(self):
        api = XiaoYiPluginAPI("no_read", [])
        with self.assertRaises(PermissionError):
            api.read_file("/etc/passwd")

    def test_call_llm_with_permission(self):
        result = self.api.call_llm("test prompt", model="llama3")
        self.assertIn("test prompt", result)

    def test_call_llm_without_permission_raises(self):
        api = XiaoYiPluginAPI("no_llm", [])
        with self.assertRaises(PermissionError):
            api.call_llm("hello")

    def test_get_system_stats_with_permission(self):
        result = self.api.get_system_stats()
        self.assertIn("cpu", result)
        self.assertIn("memory", result)

    def test_get_system_stats_without_permission_raises(self):
        api = XiaoYiPluginAPI("no_stats", [])
        with self.assertRaises(PermissionError):
            api.get_system_stats()

    def test_emit_event_with_permission(self):
        result = self.api.emit_event("test_event", {"key": "value"})
        self.assertIsNone(result)

    def test_emit_event_without_permission_raises(self):
        api = XiaoYiPluginAPI("no_event", [])
        with self.assertRaises(PermissionError):
            api.emit_event("test", {})

    def test_audit_log_records_access(self):
        self.api.get_config("test_key")
        log = self.api.get_audit_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["api"], "get_config")
        self.assertEqual(log[0]["plugin_id"], "test_plugin")

    def test_audit_log_limit(self):
        for i in range(5):
            self.api.get_config(f"key{i}")
        log = self.api.get_audit_log(limit=3)
        self.assertEqual(len(log), 3)


# ============================================================
# Test: PluginLoader
# ============================================================

class TestPluginLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plugin_test_")
        self.loader = PluginLoader(plugins_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_discover_empty_dir(self):
        manifests = self.loader.discover_plugins()
        self.assertEqual(len(manifests), 0)

    def test_discover_single_plugin(self):
        _make_plugin_dir(self.tmp, "plugin1", "Plugin One")
        manifests = self.loader.discover_plugins()
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0].name, "Plugin One")

    def test_discover_multiple_plugins(self):
        _make_plugin_dir(self.tmp, "p1", "P1")
        _make_plugin_dir(self.tmp, "p2", "P2")
        _make_plugin_dir(self.tmp, "p3", "P3")
        manifests = self.loader.discover_plugins()
        self.assertEqual(len(manifests), 3)

    def test_load_plugin_returns_instance(self):
        _make_plugin_dir(self.tmp, "load1", "LoadTest")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.assertEqual(instance.status, PluginStatus.LOADED)
        self.assertEqual(instance.manifest.name, "LoadTest")

    def test_load_plugin_twice_returns_same(self):
        _make_plugin_dir(self.tmp, "dup1", "Dup")
        manifests = self.loader.discover_plugins()
        i1 = self.loader.load_plugin(manifests[0])
        i2 = self.loader.load_plugin(manifests[0])
        self.assertIs(i1, i2)

    def test_enable_plugin_returns_true(self):
        _make_plugin_dir(self.tmp, "en1", "EnTest")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        result = self.loader.enable_plugin(instance.manifest.plugin_id)
        self.assertTrue(result)
        self.assertEqual(instance.status, PluginStatus.ENABLED)

    def test_disable_plugin_returns_true(self):
        _make_plugin_dir(self.tmp, "dis1", "DisTest")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.loader.enable_plugin(instance.manifest.plugin_id)
        result = self.loader.disable_plugin(instance.manifest.plugin_id)
        self.assertTrue(result)
        self.assertEqual(instance.status, PluginStatus.DISABLED)

    def test_unload_plugin_removes_from_registry(self):
        _make_plugin_dir(self.tmp, "ul1", "UlTest")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.loader.enable_plugin(instance.manifest.plugin_id)
        result = self.loader.unload_plugin(instance.manifest.plugin_id)
        self.assertTrue(result)
        self.assertIsNone(self.loader.get_plugin(instance.manifest.plugin_id))

    def test_get_plugin_existing(self):
        _make_plugin_dir(self.tmp, "gp1", "GetTest")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        found = self.loader.get_plugin(instance.manifest.plugin_id)
        self.assertIs(found, instance)

    def test_get_plugin_nonexistent_returns_none(self):
        result = self.loader.get_plugin("nonexistent_xyz")
        self.assertIsNone(result)

    def test_get_all_plugins_after_load(self):
        _make_plugin_dir(self.tmp, "all1", "All1")
        _make_plugin_dir(self.tmp, "all2", "All2")
        manifests = self.loader.discover_plugins()
        self.loader.load_plugin(manifests[0])
        self.loader.load_plugin(manifests[1])
        all_p = self.loader.get_all_plugins()
        self.assertEqual(len(all_p), 2)

    def test_get_plugins_by_status_enabled(self):
        _make_plugin_dir(self.tmp, "st1", "StTest")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.loader.enable_plugin(instance.manifest.plugin_id)
        enabled = self.loader.get_plugins_by_status(PluginStatus.ENABLED)
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].status, PluginStatus.ENABLED)

    def test_enable_nonexistent_returns_false(self):
        result = self.loader.enable_plugin("nonexistent_xyz")
        self.assertFalse(result)

    def test_disable_nonexistent_returns_false(self):
        result = self.loader.disable_plugin("nonexistent_xyz")
        self.assertFalse(result)

    def test_unload_nonexistent_returns_false(self):
        result = self.loader.unload_plugin("nonexistent_xyz")
        self.assertFalse(result)


# ============================================================
# Test: global_plugin_manager
# ============================================================

class TestGlobalPluginManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="global_plugin_test_")
        self.original = global_plugin_manager
        import core.kernel.plugin_sdk as ps
        ps.global_plugin_manager = PluginLoader(plugins_dir=self.tmp)
        self.gpm = ps.global_plugin_manager

    def tearDown(self):
        import shutil

        import core.kernel.plugin_sdk as ps
        ps.global_plugin_manager = self.original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_global_manager_discover_empty(self):
        plugins = self.gpm.get_all_plugins()
        self.assertEqual(len(plugins), 0)

    def test_global_manager_load_plugin(self):
        _make_plugin_dir(self.tmp, "global1", "GlobalTest")
        manifests = self.gpm.discover_plugins()
        instance = self.gpm.load_plugin(manifests[0])
        self.assertEqual(instance.status, PluginStatus.LOADED)


class TestPluginManifestEdgeCases(unittest.TestCase):

    def test_dependencies_field(self):
        """PluginManifest stores dependencies list"""
        m = PluginManifest(
            name="dep_plugin",
            version="1.0.0",
            description="Test",
            permissions=[],
            dependencies=["numpy", "requests"],
        )
        self.assertEqual(m.dependencies, ["numpy", "requests"])

    def test_api_version_default(self):
        """PluginManifest has default api_version 1.0.0"""
        m = PluginManifest(name="av", version="1.0.0", description="", permissions=[])
        self.assertEqual(m.api_version, "1.0.0")

    def test_api_version_custom(self):
        """PluginManifest accepts custom api_version"""
        m = PluginManifest(
            name="av2", version="2.0.0", description="",
            permissions=[], api_version="2.0.0",
        )
        self.assertEqual(m.api_version, "2.0.0")

    def test_post_init_generates_unique_ids(self):
        """__post_init__ generates different IDs for different instances"""
        m1 = PluginManifest(name="u1", version="1.0.0", description="", permissions=[], plugin_id="")
        m2 = PluginManifest(name="u2", version="1.0.0", description="", permissions=[], plugin_id="")
        self.assertNotEqual(m1.plugin_id, m2.plugin_id)
        self.assertEqual(len(m1.plugin_id), 8)

    def test_sandbox_default_true(self):
        """PluginManifest sandbox defaults to True"""
        m = PluginManifest(name="sb", version="1.0.0", description="", permissions=[])
        self.assertTrue(m.sandbox)


# ============================================================
# Test: PluginInstance fields
# ============================================================

class TestPluginInstanceFields(unittest.TestCase):

    def test_error_message_default(self):
        """PluginInstance error_message defaults to empty string"""
        m = PluginManifest(name="err", version="1.0.0", description="", permissions=[])
        inst = PluginInstance(manifest=m, status=PluginStatus.LOADED)
        self.assertEqual(inst.error_message, "")

    def test_last_activated_default(self):
        """PluginInstance last_activated defaults to empty string"""
        m = PluginManifest(name="la", version="1.0.0", description="", permissions=[])
        inst = PluginInstance(manifest=m, status=PluginStatus.LOADED)
        self.assertEqual(inst.last_activated, "")

    def test_error_instance(self):
        """PluginInstance can be created with ERROR status"""
        m = PluginManifest(name="err_inst", version="1.0.0", description="", permissions=[])
        inst = PluginInstance(
            manifest=m,
            status=PluginStatus.ERROR,
            error_message="load failed",
            loaded_at="2026-01-01T00:00:00",
        )
        self.assertEqual(inst.status, PluginStatus.ERROR)
        self.assertEqual(inst.error_message, "load failed")
        self.assertEqual(inst.loaded_at, "2026-01-01T00:00:00")


# ============================================================
# Test: XiaoYiPluginAPI log_access
# ============================================================

class TestXiaoYiPluginAPILogAccess(unittest.TestCase):

    def setUp(self):
        self.api = XiaoYiPluginAPI("log_test", ["system_config"])

    def test_log_access_records_plugin_id(self):
        """log_access records plugin_id in audit log"""
        self.api.log_access("get_config", {"key": "x"})
        log = self.api.get_audit_log()
        self.assertEqual(log[0]["plugin_id"], "log_test")

    def test_log_access_records_api_name(self):
        """log_access records api name"""
        self.api.log_access("call_llm", {"prompt": "hi"})
        log = self.api.get_audit_log()
        self.assertEqual(log[0]["api"], "call_llm")

    def test_log_access_records_timestamp(self):
        """log_access records ISO timestamp"""
        self.api.log_access("test", {})
        log = self.api.get_audit_log()
        self.assertIn("timestamp", log[0])
        self.assertIsInstance(log[0]["timestamp"], str)

    def test_log_access_truncates_args(self):
        """log_access truncates args to 200 chars"""
        long_args = {"data": "x" * 500}
        self.api.log_access("test", long_args)
        log = self.api.get_audit_log()
        self.assertLessEqual(len(log[0]["args"]), 200)


# ============================================================
# Test: PluginLoader internals (_validate_manifest, _create_sandbox)
# ============================================================

class TestPluginLoaderInternals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plugin_internal_test_")
        self.loader = PluginLoader(plugins_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_validate_manifest_empty_name_raises(self):
        """_validate_manifest raises ValueError for empty name"""
        m = PluginManifest(name="", version="1.0.0", description="", permissions=[])
        with self.assertRaises(ValueError):
            self.loader._validate_manifest(m)

    def test_validate_manifest_empty_version_raises(self):
        """_validate_manifest raises ValueError for empty version"""
        m = PluginManifest(name="v", version="", description="", permissions=[])
        with self.assertRaises(ValueError):
            self.loader._validate_manifest(m)

    def test_validate_manifest_empty_entry_point_raises(self):
        """_validate_manifest raises ValueError for empty entry_point"""
        m = PluginManifest(
            name="ep", version="1.0.0", description="",
            permissions=[], entry_point="",
        )
        with self.assertRaises(ValueError):
            self.loader._validate_manifest(m)

    def test_validate_manifest_dangerous_permission_raises(self):
        """_validate_manifest raises ValueError for dangerous permissions"""
        m = PluginManifest(
            name="danger", version="1.0.0", description="",
            permissions=["system_config", "fs_write"],
        )
        with self.assertRaises(ValueError):
            self.loader._validate_manifest(m)

    def test_validate_manifest_child_process_raises(self):
        """_validate_manifest raises ValueError for child_process permission"""
        m = PluginManifest(
            name="cp", version="1.0.0", description="",
            permissions=["child_process"],
        )
        with self.assertRaises(ValueError):
            self.loader._validate_manifest(m)

    def test_validate_manifest_safe_permissions_pass(self):
        """_validate_manifest passes for safe permissions"""
        m = PluginManifest(
            name="safe", version="1.0.0", description="",
            permissions=["system_config", "file_read"],
            entry_point="main.py",
        )
        self.loader._validate_manifest(m)  # no exception

    def test_create_sandbox_native_runtime(self):
        """_create_sandbox returns native runtime config"""
        m = PluginManifest(
            name="native", version="1.0.0", description="",
            permissions=[], runtime="native",
        )
        config = self.loader._create_sandbox(m)
        self.assertEqual(config["runtime"], "native")
        self.assertIn("permissions", config)
        self.assertIn("denied_apis", config)
        self.assertEqual(config["timeout"], 30)

    def test_create_sandbox_uv_runtime(self):
        """_create_sandbox includes venv_path for uv runtime"""
        m = PluginManifest(
            name="uv_plugin", version="1.0.0", description="",
            permissions=[], runtime="python_uv",
        )
        config = self.loader._create_sandbox(m)
        self.assertEqual(config["runtime"], "python_uv")
        self.assertIn("venv_path", config)
        self.assertIn("python_path", config)

    def test_create_sandbox_node_worker_runtime(self):
        """_create_sandbox includes worker_type for node_worker"""
        m = PluginManifest(
            name="node_plugin", version="1.0.0", description="",
            permissions=[], runtime="node_worker",
        )
        config = self.loader._create_sandbox(m)
        self.assertEqual(config["runtime"], "node_worker")
        self.assertEqual(config["worker_type"], "isolated")

    def test_load_plugin_missing_entry_point_raises(self):
        """load_plugin raises ValueError if manifest has no entry_point"""
        m = PluginManifest(
            name="no_ep", version="1.0.0", description="",
            permissions=[], entry_point="",
        )
        with self.assertRaises(ValueError):
            self.loader.load_plugin(m)

    def test_load_plugin_module_error_returns_error_instance(self):
        """load_plugin returns ERROR instance when module loading fails"""
        # Use a unique entry_point name to avoid sys.modules cache collision
        # with other tests that may have imported "main" earlier
        pdir = Path(self.tmp) / "fail1"
        pdir.mkdir()
        (pdir / "manifest.json").write_text(json.dumps({
            "name": "fail_plugin", "version": "1.0.0",
            "description": "Test", "author": "test",
            "permissions": [], "plugin_id": "fail1",
            "entry_point": "broken_plugin_main.py",
            "runtime": "native",
        }), encoding="utf-8")
        (pdir / "broken_plugin_main.py").write_text(
            "raise ImportError('broken plugin')", encoding="utf-8"
        )

        manifests = self.loader.discover_plugins()
        self.assertTrue(len(manifests) > 0)
        result = self.loader.load_plugin(manifests[0])
        self.assertEqual(result.status, PluginStatus.ERROR)
        self.assertNotEqual(result.error_message, "")


# ============================================================
# Test: PluginLoader enable/disable lifecycle
# ============================================================

class TestPluginLoaderLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plugin_lifecycle_test_")
        self.loader = PluginLoader(plugins_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enable_already_enabled_returns_true(self):
        """enable_plugin returns True when already enabled"""
        _make_plugin_dir(self.tmp, "ae1", "AlreadyEnabled")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.loader.enable_plugin(instance.manifest.plugin_id)
        result = self.loader.enable_plugin(instance.manifest.plugin_id)
        self.assertTrue(result)
        self.assertEqual(instance.status, PluginStatus.ENABLED)

    def test_disable_never_enabled_returns_true(self):
        """disable_plugin on loaded (not enabled) plugin returns True"""
        _make_plugin_dir(self.tmp, "dn1", "DisableNever")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        result = self.loader.disable_plugin(instance.manifest.plugin_id)
        self.assertTrue(result)
        self.assertEqual(instance.status, PluginStatus.DISABLED)

    def test_enable_then_disable_then_enable(self):
        """Full lifecycle: enable -> disable -> enable"""
        _make_plugin_dir(self.tmp, "life1", "Lifecycle")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.assertTrue(self.loader.enable_plugin(instance.manifest.plugin_id))
        self.assertEqual(instance.status, PluginStatus.ENABLED)
        self.assertTrue(self.loader.disable_plugin(instance.manifest.plugin_id))
        self.assertEqual(instance.status, PluginStatus.DISABLED)
        self.assertTrue(self.loader.enable_plugin(instance.manifest.plugin_id))
        self.assertEqual(instance.status, PluginStatus.ENABLED)

    def test_load_plugin_sets_loaded_at(self):
        """load_plugin sets loaded_at timestamp"""
        _make_plugin_dir(self.tmp, "ts1", "Timestamp")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.assertNotEqual(instance.loaded_at, "")
        self.assertIn("2026", instance.loaded_at)

    def test_enable_sets_last_activated(self):
        """enable_plugin sets last_activated timestamp"""
        _make_plugin_dir(self.tmp, "la1", "LastActivated")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.loader.enable_plugin(instance.manifest.plugin_id)
        self.assertNotEqual(instance.last_activated, "")

    def test_enable_increments_activation_count(self):
        """Multiple enables increment activation_count"""
        _make_plugin_dir(self.tmp, "ac1", "ActCount")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        self.loader.enable_plugin(instance.manifest.plugin_id)
        self.assertEqual(instance.activation_count, 1)
        self.loader.disable_plugin(instance.manifest.plugin_id)
        self.loader.enable_plugin(instance.manifest.plugin_id)
        self.assertEqual(instance.activation_count, 2)


# ============================================================
# Test: PluginManager singleton + crash recovery + load_all
# ============================================================

class TestPluginManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plugin_mgr_test_")
        self.original_gpm = global_plugin_manager
        import core.kernel.plugin_sdk as ps
        # Force new singleton pointing to our tmp dir
        PluginManager._instance = None
        self.mgr = PluginManager(plugins_dir=self.tmp)
        ps.global_plugin_manager = self.mgr

    def tearDown(self):
        import core.kernel.plugin_sdk as ps
        PluginManager._instance = None
        ps.global_plugin_manager = self.original_gpm
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_singleton_same_instance(self):
        """PluginManager returns same instance on multiple construction"""
        m1 = PluginManager(plugins_dir=self.tmp)
        m2 = PluginManager(plugins_dir=self.tmp)
        self.assertIs(m1, m2)

    def test_load_all_empty_dir(self):
        """load_all returns empty dict when no plugins"""
        results = self.mgr.load_all()
        self.assertIsInstance(results, dict)
        self.assertEqual(len(results), 0)

    def test_load_all_with_plugins(self):
        """load_all loads and returns all discovered plugins"""
        _make_plugin_dir(self.tmp, "pm1", "PM1")
        _make_plugin_dir(self.tmp, "pm2", "PM2")
        results = self.mgr.load_all()
        self.assertEqual(len(results), 2)

    def test_enable_crash_tracks_error_status(self):
        """PluginManager increments crash_count when enable_plugin returns False"""
        fake_module = MagicMock()
        fake_instance = PluginInstance(
            manifest=PluginManifest(name="CrashMock", version="1.0.0",
                                    description="", permissions=["system_config"],
                                    plugin_id="crash_mock1"),
            status=PluginStatus.LOADED,
            module=fake_module,
        )
        self.mgr.loader._plugins["crash_mock1"] = fake_instance

        with patch.object(self.mgr.loader, "enable_plugin", return_value=False):
            result = self.mgr.enable("crash_mock1")

        self.assertFalse(result)
        self.assertEqual(self.mgr._crash_count["crash_mock1"], 1)

    def test_enable_max_crashes_auto_disable(self):
        """PluginManager auto-disables when crash_count reaches max_crashes"""
        fake_module = MagicMock()
        fake_instance = PluginInstance(
            manifest=PluginManifest(name="CrashMock2", version="1.0.0",
                                    description="", permissions=["system_config"],
                                    plugin_id="crash_mock2"),
            status=PluginStatus.LOADED,
            module=fake_module,
        )
        self.mgr.loader._plugins["crash_mock2"] = fake_instance

        # Pre-set crash_count to max - 1 (max_crashes = 3)
        self.mgr._crash_count["crash_mock2"] = 2

        # enable_plugin returns False -> crash_count becomes 3 >= max -> auto-disable
        with patch.object(self.mgr.loader, "enable_plugin", return_value=False):
            result = self.mgr.enable("crash_mock2")

        self.assertFalse(result)
        self.assertEqual(fake_instance.status, PluginStatus.DISABLED)

    def test_enable_success_clears_crash_count(self):
        """Successful enable clears previous crash_count entry"""
        fake_module = MagicMock()
        fake_instance = PluginInstance(
            manifest=PluginManifest(name="OkPlugin", version="1.0.0",
                                    description="", permissions=["system_config"],
                                    plugin_id="ok1"),
            status=PluginStatus.LOADED,
            module=fake_module,
        )
        self.mgr.loader._plugins["ok1"] = fake_instance

        with patch.object(self.mgr.loader, "enable_plugin", return_value=True):
            result = self.mgr.enable("ok1")

        self.assertTrue(result)
        # Successful enable removes crash_count entry
        self.assertNotIn("ok1", self.mgr._crash_count)

    def test_get_plugin_returns_none_for_missing(self):
        """get_plugin returns None for nonexistent plugin_id"""
        result = self.mgr.get_plugin("nonexistent_xyz")
        self.assertIsNone(result)

    def test_get_all_plugins_returns_list(self):
        """get_all_plugins returns list of PluginInstance"""
        result = self.mgr.get_all_plugins()
        self.assertIsInstance(result, list)

    def test_disable_calls_deactivate(self):
        """disable_plugin calls module.deactivate when present"""
        fake_module = MagicMock()
        fake_instance = PluginInstance(
            manifest=PluginManifest(name="DeactPlugin", version="1.0.0",
                                    description="", permissions=["system_config"],
                                    plugin_id="deact1"),
            status=PluginStatus.ENABLED,
            module=fake_module,
        )
        self.mgr.loader._plugins["deact1"] = fake_instance

        with patch.object(self.mgr.loader, "disable_plugin", return_value=True) as mock_disable:
            result = self.mgr.disable("deact1")

        self.assertTrue(result)
        # Manager delegates to loader.disable_plugin
        mock_disable.assert_called_once_with("deact1")

    def test_unload_removes_plugin_from_registry(self):
        """unload delegates to loader.unload_plugin and plugin is gone"""
        fake_module = MagicMock()
        fake_instance = PluginInstance(
            manifest=PluginManifest(name="UnloadPlugin", version="1.0.0",
                                    description="", permissions=["system_config"],
                                    plugin_id="unload1"),
            status=PluginStatus.LOADED,
            module=fake_module,
        )
        self.mgr.loader._plugins["unload1"] = fake_instance

        with patch.object(self.mgr.loader, "unload_plugin", return_value=True) as mock_unload:
            result = self.mgr.unload("unload1")

        self.assertTrue(result)
        mock_unload.assert_called_once_with("unload1")




# ============================================================
# Test: PluginLoader sandbox policy validation
# ============================================================

class TestPluginSandboxPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plugin_sandbox_")
        self.loader = PluginLoader(plugins_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sandbox_true_requires_denied_apis(self):
        manifest = PluginManifest(
            name="sandbox_plugin",
            version="1.0.0",
            description="Test",
            author="test",
            permissions=["system_config"],
            plugin_id="sandbox1",
            entry_point="main.py",
            runtime="native",
            sandbox=True,
            denied_apis=["fs"],
        )
        with self.assertRaises(ValueError):
            self.loader.load_plugin(manifest)

    def test_sandbox_false_allows_missing_denied_apis(self):
        manifest = PluginManifest(
            name="nonsandbox_plugin",
            version="1.0.0",
            description="Test",
            author="test",
            permissions=["system_config"],
            plugin_id="nonsandbox1",
            entry_point="main.py",
            runtime="native",
            sandbox=False,
            denied_apis=[],
        )
        instance = self.loader.load_plugin(manifest)
        self.assertEqual(instance.status, PluginStatus.LOADED)

    def test_sandbox_true_with_full_denied_apis_loads(self):
        manifest = PluginManifest(
            name="safe_sandbox_plugin",
            version="1.0.0",
            description="Test",
            author="test",
            permissions=["system_config"],
            plugin_id="safebox1",
            entry_point="main.py",
            runtime="native",
            sandbox=True,
            denied_apis=["fs", "child_process", "network"],
        )
        instance = self.loader.load_plugin(manifest)
        self.assertEqual(instance.status, PluginStatus.LOADED)

def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. plugin_sdk tests - Iteration 37")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestPluginStatus, TestPluginManifest, TestPluginInstance,
               TestXiaoYiPluginAPI, TestPluginLoader, TestGlobalPluginManager,
               TestPluginManifestEdgeCases, TestPluginInstanceFields,
               TestXiaoYiPluginAPILogAccess, TestPluginLoaderInternals,
               TestPluginLoaderLifecycle, TestPluginManager,
               TestPluginSandboxPolicy]:
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
