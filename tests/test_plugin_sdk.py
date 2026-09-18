# -*- coding: utf-8 -*-
"""
Additional plugin_sdk tests - Iteration 37
Tests PluginManager singleton/crash recovery, PluginLoader internals, PluginManifest edge cases
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.contracts.plugin_worker_protocol import LifecycleAction, PluginBrokerRequest
from core.kernel import plugin_sdk as plugin_sdk_module
from core.kernel.event_bus import EventBus
from core.kernel.plugin_broker import PluginBroker
from core.kernel.plugin_sdk import (
    MAX_PLUGIN_MANIFEST_BYTES,
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
        "runtime": "python_worker",
    }
    (pdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pdir / "main.py").write_text(
        "def activate(api): pass\ndef deactivate(): pass\ndef cleanup(): pass",
        encoding="utf-8"
    )
    return pdir


def _make_test_loader(plugins_dir):
    broker = PluginBroker(EventBus(), grants={})
    broker.register_event_emit_handler()
    return PluginLoader(plugins_dir, broker, runtime_factory=_CoordinatorRuntime)


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
        self.assertEqual(RuntimeType.PYTHON_WORKER.value, "python_worker")


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
        def broker_call(capability, arguments):
            if capability == "config.get":
                result = arguments.get("default")
            elif capability == "file.read":
                result = "broker-owned-content"
            elif capability == "llm.call":
                result = f"broker:{arguments['prompt']}"
            elif capability == "event.emit":
                result = None
            else:
                result = {"cpu": 1, "memory": 2}
            return SimpleNamespace(allowed=True, error="", result=result)

        self.api = XiaoYiPluginAPI(
            "test_plugin",
            ["system_config", "file_read", "llm_access", "event_bus", "system_monitor"],
            broker_call=broker_call,
        )

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
        result = self.api.read_file("broker/path.txt")
        self.assertEqual(result, "broker-owned-content")

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

    def test_audit_history_evicts_oldest_entries(self):
        for index in range(1005):
            self.api.log_access(f"call-{index}", {})

        log = self.api.get_audit_log(limit=5000)

        self.assertEqual(len(log), 1000)
        self.assertEqual(log[0]["api"], "call-5")
        self.assertEqual(log[-1]["api"], "call-1004")

    def test_audit_snapshots_do_not_alias_internal_entries(self):
        self.api.log_access("original", {})
        snapshot = self.api.get_audit_log(limit=1)
        snapshot[0]["api"] = "tampered"

        self.assertEqual(self.api.get_audit_log(limit=1)[0]["api"], "original")

    def test_audit_sink_and_local_history_have_separate_ownership(self):
        sink_entries = []

        def mutating_sink(entry):
            sink_entries.append(entry)
            entry["api"] = "sink-mutated"

        api = XiaoYiPluginAPI("sink-test", [], audit_sink=mutating_sink)
        api.log_access("original", {})

        self.assertEqual(api.get_audit_log(limit=1)[0]["api"], "original")
        self.assertEqual(sink_entries[0]["api"], "sink-mutated")

        local_snapshot = api.get_audit_log(limit=1)
        local_snapshot[0]["api"] = "snapshot-mutated"
        self.assertEqual(sink_entries[0]["api"], "sink-mutated")

    def test_audit_limit_is_a_non_negative_plain_integer(self):
        self.assertEqual(self.api.get_audit_log(limit=0), [])
        for invalid_limit in (-1, True, 1.5, "1"):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    self.api.get_audit_log(limit=invalid_limit)


# ============================================================
# Test: PluginLoader
# ============================================================

class TestPluginLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plugin_test_")
        self.loader = _make_test_loader(self.tmp)

    def tearDown(self):
        import shutil
        self.loader.close()
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
        ps.global_plugin_manager = PluginManager(
            self.tmp,
            event_bus=EventBus(),
            grants={},
            runtime_factory=_CoordinatorRuntime,
        )
        self.gpm = ps.global_plugin_manager

    def tearDown(self):
        import shutil

        import core.kernel.plugin_sdk as ps
        self.gpm.close()
        ps.global_plugin_manager = self.original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_global_manager_discover_empty(self):
        plugins = self.gpm.get_all_plugins()
        self.assertEqual(len(plugins), 0)

    def test_global_manager_load_plugin(self):
        _make_plugin_dir(self.tmp, "global1", "GlobalTest")
        manifests = self.gpm.discover()
        instance = self.gpm.load(manifests[0])
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
        self.loader = _make_test_loader(self.tmp)

    def tearDown(self):
        self.loader.close()
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

    def test_legacy_runtime_returns_unsupported_error_instance(self):
        """Legacy runtime content is never imported by the loader."""
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
        self.assertEqual(result.error_message, "PLUGIN_RUNTIME_UNSUPPORTED")


# ============================================================
# Test: PluginLoader enable/disable lifecycle
# ============================================================

class TestPluginLoaderLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="plugin_lifecycle_test_")
        self.loader = _make_test_loader(self.tmp)

    def tearDown(self):
        self.loader.close()
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

    def test_disable_never_enabled_returns_false(self):
        """A loaded Worker must be activated before deactivation."""
        _make_plugin_dir(self.tmp, "dn1", "DisableNever")
        manifests = self.loader.discover_plugins()
        instance = self.loader.load_plugin(manifests[0])
        result = self.loader.disable_plugin(instance.manifest.plugin_id)
        self.assertFalse(result)
        self.assertEqual(instance.status, PluginStatus.LOADED)

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
        self.mgr = PluginManager(
            self.tmp,
            event_bus=EventBus(),
            grants={},
            runtime_factory=_CoordinatorRuntime,
        )
        ps.global_plugin_manager = self.mgr

    def tearDown(self):
        import core.kernel.plugin_sdk as ps
        self.mgr.close()
        ps.global_plugin_manager = self.original_gpm
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_each_service_gets_an_independent_manager(self):
        """PluginManager is a normal per-service owner."""
        m1 = PluginManager(self.tmp, event_bus=EventBus(), grants={}, runtime_factory=_CoordinatorRuntime)
        m2 = PluginManager(self.tmp, event_bus=EventBus(), grants={}, runtime_factory=_CoordinatorRuntime)
        self.addCleanup(m1.close)
        self.addCleanup(m2.close)
        self.assertIsNot(m1, m2)

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

    def test_enable_failures_are_counted_without_in_process_status_mutation(self):
        """The manager never mutates a plugin through an in-process module."""
        fake_module = MagicMock()
        fake_instance = PluginInstance(
            manifest=PluginManifest(name="CrashMock2", version="1.0.0",
                                    description="", permissions=["system_config"],
                                    plugin_id="crash_mock2"),
            status=PluginStatus.LOADED,
            module=fake_module,
        )
        self.mgr.loader._plugins["crash_mock2"] = fake_instance

        self.mgr._crash_count["crash_mock2"] = 2

        with patch.object(self.mgr.loader, "enable_plugin", return_value=False):
            result = self.mgr.enable("crash_mock2")

        self.assertFalse(result)
        self.assertEqual(self.mgr._crash_count["crash_mock2"], 3)
        self.assertEqual(fake_instance.status, PluginStatus.LOADED)

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
        self.loader = _make_test_loader(self.tmp)

    def tearDown(self):
        import shutil
        self.loader.close()
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
            self.loader._validate_sandbox_policy(manifest)

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
        self.loader._validate_sandbox_policy(manifest)

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
        self.loader._validate_sandbox_policy(manifest)


class _CoordinatorRuntime:
    created = []

    def __init__(self, plugin_root, load_spec, broker):
        self.plugin_root = Path(plugin_root)
        self.load_spec = load_spec
        self.broker = broker
        self.actions = []
        self.closed = False
        self.snapshot = SimpleNamespace(
            plugin_id=self.plugin_root.name,
            pid=43000 + len(type(self).created),
            generation=load_spec.generation,
            termination_confirmed=False,
        )
        type(self).created.append(self)

    def start(self):
        return self.snapshot

    def invoke(self, action):
        self.actions.append(action)
        statuses = {
            LifecycleAction.LOAD: "loaded",
            LifecycleAction.ACTIVATE: "enabled",
            LifecycleAction.DEACTIVATE: "disabled",
            LifecycleAction.CLEANUP: "unloaded",
            LifecycleAction.SHUTDOWN: "unloaded",
        }
        if action is LifecycleAction.SHUTDOWN:
            self.snapshot.termination_confirmed = True
        return SimpleNamespace(success=True, status=statuses[action], error="")

    def close(self):
        self.closed = True
        self.snapshot.termination_confirmed = True


class TestPluginWorkerCoordinator(unittest.TestCase):
    def setUp(self):
        _CoordinatorRuntime.created = []
        self.tmp = tempfile.TemporaryDirectory(prefix="plugin_worker_sdk_")
        self.bus = EventBus()
        self.broker = PluginBroker(self.bus, grants={})
        self.loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=_CoordinatorRuntime,
        )

    def tearDown(self):
        self.loader.close()
        self.tmp.cleanup()

    def _plugin(self, plugin_id, *, runtime="python_worker", entry_point="plugin.py"):
        root = Path(self.tmp.name) / plugin_id
        root.mkdir()
        manifest = {
            "name": plugin_id,
            "version": "1.0.0",
            "description": "worker fixture",
            "permissions": [],
            "runtime": runtime,
            "entry_point": entry_point,
            "plugin_id": plugin_id,
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "plugin.py").write_text("def activate(api):\n    pass\n", encoding="utf-8")
        return root

    def _manifest(self, plugin_id):
        return next(
            manifest
            for manifest in self.loader.discover_plugins()
            if manifest.plugin_id == plugin_id
        )

    def test_discovery_accepts_exact_entry_budget_in_name_order(self):
        self.assertEqual(plugin_sdk_module.MAX_PLUGIN_DISCOVERY_ENTRIES, 8_192)
        self._plugin("zeta-entry")
        self._plugin("alpha-entry")

        with patch.object(
            plugin_sdk_module,
            "MAX_PLUGIN_DISCOVERY_ENTRIES",
            2,
        ):
            found = self.loader.discover_plugins()

        self.assertEqual(
            [manifest.plugin_id for manifest in found],
            ["alpha-entry", "zeta-entry"],
        )

    def test_discovery_overflow_clears_snapshot_before_reading_manifests(self):
        self._plugin("previous-entry")
        self.assertEqual(
            [manifest.plugin_id for manifest in self.loader.discover_plugins()],
            ["previous-entry"],
        )
        self._plugin("second-entry")
        self._plugin("third-entry")

        with patch.object(
            plugin_sdk_module,
            "MAX_PLUGIN_DISCOVERY_ENTRIES",
            2,
        ), patch.object(
            self.loader,
            "_read_bounded_manifest",
            wraps=self.loader._read_bounded_manifest,
        ) as read_manifest:
            found = self.loader.discover_plugins()

        self.assertEqual(found, [])
        self.assertEqual(self.loader._manifests, [])
        read_manifest.assert_not_called()

    def test_discovery_stops_scandir_at_first_over_budget_entry(self):
        roots = [Path(self.tmp.name) / f"entry-{index}" for index in range(3)]
        calls = []

        class _GuardedScanner:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                calls.append(len(calls) + 1)
                if len(calls) > len(roots):
                    raise AssertionError("scanner advanced beyond first overflow")
                return SimpleNamespace(path=str(roots[len(calls) - 1]))

        scanner = _GuardedScanner()
        with patch.object(
            plugin_sdk_module,
            "MAX_PLUGIN_DISCOVERY_ENTRIES",
            2,
        ), patch.dict(
            plugin_sdk_module.__dict__,
            {"os": SimpleNamespace(scandir=lambda _path: scanner)},
        ):
            found = self.loader.discover_plugins()

        self.assertEqual(found, [])
        self.assertEqual(calls, [1, 2, 3])

    def test_load_owns_worker_identity_and_exact_reload_returns_existing_instance(self):
        self._plugin("worker-one")
        manifest = self._manifest("worker-one")

        first = self.loader.load_plugin(manifest)
        second = self.loader.load_plugin(manifest)

        self.assertIs(first, second)
        self.assertEqual(first.status, PluginStatus.LOADED)
        self.assertIsNone(first.module)
        self.assertEqual(first.worker_pid, _CoordinatorRuntime.created[0].snapshot.pid)
        self.assertEqual(first.generation, 1)
        self.assertEqual(len(_CoordinatorRuntime.created), 1)

    def test_concurrent_exact_loads_own_one_worker_generation(self):
        self._plugin("concurrent-load")
        manifest = self._manifest("concurrent-load")
        entered = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        second_done = threading.Event()
        results = []
        errors = []

        class GatedStartRuntime(_CoordinatorRuntime):
            def start(self):
                if not entered.is_set():
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("test did not release the first load")
                return super().start()

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=GatedStartRuntime,
        )

        def load_once(
            mark_done: threading.Event | None = None,
            started: threading.Event | None = None,
        ):
            if started is not None:
                started.set()
            try:
                results.append(loader.load_plugin(manifest))
            except BaseException as error:
                errors.append(error)
            finally:
                if mark_done is not None:
                    mark_done.set()

        first = threading.Thread(target=load_once, name="plugin-load-first")
        second = threading.Thread(
            target=load_once,
            args=(second_done, second_started),
            name="plugin-load-second",
        )
        try:
            first.start()
            self.assertTrue(entered.wait(2))
            second.start()
            self.assertTrue(second_started.wait(2))
            self.assertFalse(second_done.wait(0.5))
        finally:
            release.set()
            first.join(timeout=2)
            if second.ident is not None:
                second.join(timeout=2)
            loader.close()

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])
        self.assertEqual(len(GatedStartRuntime.created), 1)
        self.assertEqual(results[0].generation, 1)

    def test_discovery_bounds_manifest_file_reads(self):
        self._plugin("valid-manifest")
        oversized = Path(self.tmp.name) / "oversized-manifest"
        oversized.mkdir()
        (oversized / "manifest.json").write_bytes(
            b"{}" + b" " * MAX_PLUGIN_MANIFEST_BYTES
        )

        original_open = Path.open
        read_sizes = []

        class _ReadGuard:
            def __init__(self, handle):
                self._handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._handle.close()
                return False

            def read(self, size=-1):
                read_sizes.append(size)
                return self._handle.read(size)

        def guarded_open(path, mode="r", *args, **kwargs):
            handle = original_open(path, mode, *args, **kwargs)
            if path.name != "manifest.json":
                return handle
            if mode != "rb":
                handle.close()
                raise AssertionError("Manifest reads must use binary mode")
            return _ReadGuard(handle)

        with patch.object(Path, "open", guarded_open):
            found = self.loader.discover_plugins()

        self.assertEqual([manifest.plugin_id for manifest in found], ["valid-manifest"])
        self.assertEqual(read_sizes, [MAX_PLUGIN_MANIFEST_BYTES + 1])

    def test_bounded_manifest_accepts_exact_byte_limit(self):
        root = self._plugin("exact-limit")
        manifest_path = root / "manifest.json"
        raw = manifest_path.read_bytes()
        manifest_path.write_bytes(
            raw + b" " * (MAX_PLUGIN_MANIFEST_BYTES - len(raw))
        )

        data = self.loader._read_bounded_manifest(manifest_path)

        self.assertEqual(manifest_path.stat().st_size, MAX_PLUGIN_MANIFEST_BYTES)
        self.assertEqual(data["plugin_id"], "exact-limit")

    def test_bounded_manifest_sentinel_rejects_growth_after_size_check(self):
        root = self._plugin("growing-manifest")
        manifest_path = root / "manifest.json"
        manifest_path.write_bytes(b"{}" + b" " * MAX_PLUGIN_MANIFEST_BYTES)
        real_stat = manifest_path.stat()

        with patch.object(
            Path,
            "stat",
            return_value=SimpleNamespace(st_size=MAX_PLUGIN_MANIFEST_BYTES),
        ):
            with self.assertRaisesRegex(ValueError, "manifest is too large"):
                self.loader._read_bounded_manifest(manifest_path)

        self.assertGreater(real_stat.st_size, MAX_PLUGIN_MANIFEST_BYTES)

    def test_discovery_isolates_recursive_manifest_json(self):
        self._plugin("valid-manifest")
        recursive = Path(self.tmp.name) / "deep-manifest"
        recursive.mkdir()
        nested = "[" * 5000 + "0" + "]" * 5000
        payload = (
            "{" +
            '"plugin_id":"deep-manifest",' +
            '"name":"deep",' +
            '"version":"1.0.0",' +
            '"description":"",' +
            '"entry_point":"plugin.py",' +
            '"nested":' + nested +
            "}"
        )
        self.assertLess(len(payload.encode("utf-8")), MAX_PLUGIN_MANIFEST_BYTES)
        (recursive / "manifest.json").write_text(
            payload,
            encoding="utf-8",
        )

        found = self.loader.discover_plugins()

        self.assertEqual([manifest.plugin_id for manifest in found], ["valid-manifest"])

    def test_active_load_identity_is_a_frozen_snapshot_of_validated_values(self):
        root = self._plugin("identity-snapshot")
        manifest = self._manifest("identity-snapshot")

        instance = self.loader.load_plugin(manifest)
        identity = instance._load_identity

        self.assertEqual(identity.canonical_root, root.resolve(strict=True))
        self.assertEqual(identity.entry_point, "plugin.py")
        self.assertEqual(identity.runtime, "python_worker")
        self.assertEqual(identity.permissions, ())
        self.assertEqual(identity.api_version, "1.0.0")
        self.assertEqual(identity.generation, 1)
        with self.assertRaises(FrozenInstanceError):
            identity.runtime = "native"

    def test_existing_instance_rejects_runtime_changed_on_public_manifest(self):
        self._plugin("changed-runtime")
        manifest = self._manifest("changed-runtime")
        self.loader.load_plugin(manifest)
        manifest.runtime = "native"

        with self.assertRaises(ValueError):
            self.loader.load_plugin(manifest)

    def test_existing_instance_rejects_permissions_changed_on_public_manifest(self):
        self._plugin("changed-permissions")
        manifest = self._manifest("changed-permissions")
        self.loader.load_plugin(manifest)
        manifest.permissions.append("event_bus")

        with self.assertRaises(ValueError):
            self.loader.load_plugin(manifest)

    def test_existing_instance_rejects_api_version_changed_on_public_manifest(self):
        self._plugin("changed-api-version")
        manifest = self._manifest("changed-api-version")
        self.loader.load_plugin(manifest)
        manifest.api_version = "2.0.0"

        with self.assertRaises(ValueError):
            self.loader.load_plugin(manifest)

    def test_worker_pid_is_zero_when_snapshot_access_fails(self):
        manifest = PluginManifest(
            name="broken-snapshot",
            version="1.0.0",
            description="",
        )

        for error_type in (RuntimeError, OSError):
            with self.subTest(error_type=error_type):
                class BrokenSnapshotRuntime:
                    @property
                    def snapshot(self):
                        raise error_type("snapshot unavailable")

                instance = PluginInstance(
                    manifest=manifest,
                    status=PluginStatus.LOADED,
                    _runtime=BrokenSnapshotRuntime(),
                )
                self.assertEqual(instance.worker_pid, 0)

    def test_discovery_replaces_the_owned_manifest_snapshot(self):
        self._plugin("owned-manifest")

        first = self.loader.discover_plugins()
        second = self.loader.discover_plugins()

        self.assertIs(self.loader._manifests, second)
        self.assertIsNot(first[0], second[0])
        self.assertEqual([manifest.plugin_id for manifest in second], ["owned-manifest"])
        self.assertFalse(hasattr(self.loader, "_manifest_roots"))

    def test_discovery_skips_strictly_malformed_manifest_siblings(self):
        self._plugin("valid-manifest")
        base = {
            "name": "invalid fixture",
            "version": "1.0.0",
            "description": "",
            "permissions": [],
            "denied_apis": ["fs", "child_process", "network"],
            "runtime": "python_worker",
            "sandbox": True,
            "entry_point": "plugin.py",
            "dependencies": [],
            "api_version": "1.0.0",
        }
        malformed = {
            "missing-id": {},
            "mismatched-id": {"plugin_id": "different-id"},
            "bad-name": {"plugin_id": "bad-name", "name": 1},
            "bad-entrypoint": {"plugin_id": "bad-entrypoint", "entry_point": 1},
            "bad-permissions": {
                "plugin_id": "bad-permissions",
                "permissions": "event_bus",
            },
            "bad-sandbox": {"plugin_id": "bad-sandbox", "sandbox": "false"},
            "bad-dependency": {
                "plugin_id": "bad-dependency",
                "dependencies": [1],
            },
            "dangerous-permission": {
                "plugin_id": "dangerous-permission",
                "permissions": ["child_process"],
            },
            "incomplete-denials": {
                "plugin_id": "incomplete-denials",
                "denied_apis": ["fs"],
            },
        }
        for directory_name, overrides in malformed.items():
            root = Path(self.tmp.name) / directory_name
            root.mkdir()
            manifest = {**base, **overrides}
            (root / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            (root / "plugin.py").write_text("VALUE = 1\n", encoding="utf-8")

        first = self.loader.discover_plugins()
        second = self.loader.discover_plugins()

        self.assertEqual(
            [manifest.plugin_id for manifest in first],
            ["valid-manifest"],
        )
        self.assertEqual(
            [manifest.plugin_id for manifest in second],
            ["valid-manifest"],
        )

    def test_manifest_validation_does_not_repair_non_string_plugin_ids(self):
        for invalid_id in (None, False, 0):
            with self.subTest(plugin_id=invalid_id):
                manifest = PluginManifest(
                    name="invalid-id",
                    version="1.0.0",
                    description="",
                    permissions=[],
                    runtime="native",
                    entry_point="plugin.py",
                    plugin_id=invalid_id,
                )

                with self.assertRaisesRegex(ValueError, "plugin_id is invalid"):
                    self.loader._validate_manifest(manifest)

    def test_same_id_with_changed_entrypoint_is_rejected(self):
        self._plugin("worker-two")
        manifest = self._manifest("worker-two")
        self.loader.load_plugin(manifest)

        with self.assertRaises(ValueError):
            self.loader.load_plugin(replace(manifest, entry_point="other.py"))

    def test_same_id_from_changed_root_is_rejected(self):
        self._plugin("worker-three")
        other = self._plugin("other-root")
        manifest = self._manifest("worker-three")
        self.loader.load_plugin(manifest)
        duplicate = replace(self._manifest("other-root"), plugin_id="worker-three")
        duplicate._plugin_root = other

        with self.assertRaises(ValueError):
            self.loader.load_plugin(duplicate)

    def test_runtime_generation_mismatch_becomes_error_and_is_reaped(self):
        self._plugin("bad-generation")

        class WrongGenerationRuntime(_CoordinatorRuntime):
            def start(self):
                self.snapshot.generation += 1
                return self.snapshot

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=WrongGenerationRuntime,
        )
        instance = loader.load_plugin(
            next(m for m in loader.discover_plugins() if m.plugin_id == "bad-generation")
        )
        self.addCleanup(loader.close)

        self.assertEqual(instance.status, PluginStatus.ERROR)
        self.assertIn("PLUGIN_RUNTIME_IDENTITY_MISMATCH", instance.error_message)
        self.assertTrue(WrongGenerationRuntime.created[-1].snapshot.termination_confirmed)

    def test_start_interrupt_closes_worker_and_rethrows_original_exception(self):
        self._plugin("start-interrupted")
        interrupt = KeyboardInterrupt("stop startup")

        class InterruptedRuntime(_CoordinatorRuntime):
            def start(self):
                raise interrupt

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=InterruptedRuntime,
        )
        manifest = next(
            m
            for m in loader.discover_plugins()
            if m.plugin_id == "start-interrupted"
        )

        with self.assertRaises(KeyboardInterrupt) as raised:
            loader.load_plugin(manifest)

        runtime = InterruptedRuntime.created[-1]
        self.assertIs(raised.exception, interrupt)
        self.assertTrue(runtime.closed)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertIsNone(loader.get_plugin("start-interrupted"))

    def test_load_interrupt_closes_worker_and_rethrows_original_exception(self):
        self._plugin("load-interrupted")
        interrupt = KeyboardInterrupt("stop load")

        class InterruptedRuntime(_CoordinatorRuntime):
            def invoke(self, action):
                if action is LifecycleAction.LOAD:
                    self.actions.append(action)
                    raise interrupt
                return super().invoke(action)

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=InterruptedRuntime,
        )
        manifest = next(
            m
            for m in loader.discover_plugins()
            if m.plugin_id == "load-interrupted"
        )

        with self.assertRaises(KeyboardInterrupt) as raised:
            loader.load_plugin(manifest)

        runtime = InterruptedRuntime.created[-1]
        self.assertIs(raised.exception, interrupt)
        self.assertTrue(runtime.closed)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertIsNone(loader.get_plugin("load-interrupted"))

    def test_load_interrupt_retains_unconfirmed_worker_and_rethrows_original_exception(self):
        self._plugin("load-unreaped")
        interrupt = KeyboardInterrupt("stop load")

        class UnreapedInterruptedRuntime(_CoordinatorRuntime):
            def invoke(self, action):
                if action is LifecycleAction.LOAD:
                    self.actions.append(action)
                    raise interrupt
                return super().invoke(action)

            def close(self):
                self.closed = True

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=UnreapedInterruptedRuntime,
        )
        self.addCleanup(loader.close)
        manifest = next(
            m
            for m in loader.discover_plugins()
            if m.plugin_id == "load-unreaped"
        )

        with self.assertRaises(KeyboardInterrupt) as raised:
            loader.load_plugin(manifest)

        runtime = UnreapedInterruptedRuntime.created[-1]
        instance = loader.get_plugin("load-unreaped")
        self.assertIs(raised.exception, interrupt)
        self.assertTrue(runtime.closed)
        self.assertIsNotNone(instance)
        self.assertEqual(instance.status, PluginStatus.ERROR)
        self.assertIs(instance._runtime, runtime)
        self.assertIn(
            "PLUGIN_WORKER_TERMINATION_UNCONFIRMED",
            instance.error_message,
        )

    def test_ordinary_load_failure_retains_worker_when_close_is_interrupted(self):
        cases = (
            ("start", KeyboardInterrupt("interrupt close after start failure")),
            ("load", SystemExit("interrupt close after load failure")),
        )
        for failure_phase, close_interrupt in cases:
            with self.subTest(failure_phase=failure_phase):
                plugin_id = f"ordinary-{failure_phase}-failure"
                self._plugin(plugin_id)

                class CloseInterruptedRuntime(_CoordinatorRuntime):
                    def __init__(self, plugin_root, load_spec, broker):
                        super().__init__(plugin_root, load_spec, broker)
                        self.failure_phase = failure_phase
                        self.close_interrupt = close_interrupt
                        self.close_calls = 0

                    def start(self):
                        if self.failure_phase == "start":
                            raise RuntimeError("ordinary start failure")
                        return super().start()

                    def invoke(self, action):
                        if (
                            self.failure_phase == "load"
                            and action is LifecycleAction.LOAD
                        ):
                            self.actions.append(action)
                            raise RuntimeError("ordinary load failure")
                        return super().invoke(action)

                    def close(self):
                        self.closed = True
                        self.close_calls += 1
                        if self.close_calls == 1:
                            raise self.close_interrupt
                        return super().close()

                loader = PluginLoader(
                    self.tmp.name,
                    self.broker,
                    runtime_factory=CloseInterruptedRuntime,
                )
                self.addCleanup(loader.close)
                manifest = next(
                    manifest
                    for manifest in loader.discover_plugins()
                    if manifest.plugin_id == plugin_id
                )

                with self.assertRaises(type(close_interrupt)) as raised:
                    loader.load_plugin(manifest)

                runtime = CloseInterruptedRuntime.created[-1]
                instance = loader.get_plugin(plugin_id)
                self.assertIs(raised.exception, close_interrupt)
                self.assertTrue(runtime.closed)
                self.assertIsNotNone(instance)
                self.assertEqual(instance.status, PluginStatus.ERROR)
                self.assertIs(instance._runtime, runtime)
                self.assertIn(
                    "PLUGIN_WORKER_TERMINATION_UNCONFIRMED",
                    instance.error_message,
                )

    def test_invalid_root_and_entrypoint_are_rejected_before_worker_start(self):
        outside = Path(self.tmp.name).parent / "outside-plugin.py"
        outside.write_text("pass\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        bad_root = PluginManifest(
            name="escape",
            version="1.0.0",
            description="",
            plugin_id="../escape",
            runtime="python_worker",
            entry_point="plugin.py",
        )
        with self.assertRaises(ValueError):
            self.loader.load_plugin(bad_root)

        self._plugin("bad-entry")
        bad_entry = replace(self._manifest("bad-entry"), entry_point="../outside-plugin.py")
        with self.assertRaises(ValueError):
            self.loader.load_plugin(bad_entry)
        self.assertEqual(_CoordinatorRuntime.created, [])

    def test_legacy_runtime_is_discovered_without_import_and_is_not_executable(self):
        root = self._plugin("legacy", runtime="native")
        marker = root / "imported.txt"
        (root / "plugin.py").write_text(
            "from pathlib import Path\nPath(__file__).with_name('imported.txt').write_text('bad')\n",
            encoding="utf-8",
        )

        instance = self.loader.load_plugin(self._manifest("legacy"))

        self.assertEqual(instance.status, PluginStatus.ERROR)
        self.assertEqual(instance.error_message, "PLUGIN_RUNTIME_UNSUPPORTED")
        self.assertFalse(marker.exists())
        self.assertEqual(_CoordinatorRuntime.created, [])

    def test_unload_missing_returns_false(self):
        self.assertFalse(self.loader.unload_plugin("missing"))

    def test_unconfirmed_shutdown_retains_error_instance_and_blocks_replacement(self):
        self._plugin("unreaped")

        class UnreapedRuntime(_CoordinatorRuntime):
            def invoke(self, action):
                if action is LifecycleAction.SHUTDOWN:
                    self.actions.append(action)
                    raise RuntimeError("shutdown failed")
                return super().invoke(action)

            def close(self):
                self.closed = True

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=UnreapedRuntime,
        )
        manifest = next(m for m in loader.discover_plugins() if m.plugin_id == "unreaped")
        instance = loader.load_plugin(manifest)

        self.assertFalse(loader.unload_plugin("unreaped"))
        self.assertIs(loader.get_plugin("unreaped"), instance)
        self.assertEqual(instance.status, PluginStatus.ERROR)
        self.assertIn("PLUGIN_WORKER_TERMINATION_UNCONFIRMED", instance.error_message)
        self.assertIs(loader.load_plugin(manifest), instance)

    def test_cleanup_interrupt_still_attempts_shutdown_and_close_before_rethrow(self):
        self._plugin("cleanup-interrupted")
        cleanup_interrupt = KeyboardInterrupt("stop cleanup")
        shutdown_interrupt = SystemExit("stop shutdown")

        class InterruptedRuntime(_CoordinatorRuntime):
            def invoke(self, action):
                self.actions.append(action)
                if action is LifecycleAction.CLEANUP:
                    raise cleanup_interrupt
                if action is LifecycleAction.SHUTDOWN:
                    raise shutdown_interrupt
                return super().invoke(action)

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=InterruptedRuntime,
        )
        manifest = next(
            m
            for m in loader.discover_plugins()
            if m.plugin_id == "cleanup-interrupted"
        )
        instance = loader.load_plugin(manifest)

        with self.assertRaises(KeyboardInterrupt) as raised:
            loader.unload_plugin("cleanup-interrupted")

        runtime = InterruptedRuntime.created[-1]
        self.assertIs(raised.exception, cleanup_interrupt)
        self.assertIn(LifecycleAction.CLEANUP, runtime.actions)
        self.assertIn(LifecycleAction.SHUTDOWN, runtime.actions)
        self.assertTrue(runtime.closed)
        self.assertTrue(runtime.snapshot.termination_confirmed)
        self.assertEqual(instance.status, PluginStatus.UNLOADED)
        self.assertIsNone(loader.get_plugin("cleanup-interrupted"))

    def test_unload_probe_failure_does_not_replace_original_control_exception(self):
        cases = (
            (
                KeyboardInterrupt("stop cleanup"),
                RuntimeError("termination probe failed"),
            ),
            (
                SystemExit("stop cleanup"),
                OSError("termination probe unavailable"),
            ),
        )
        for cleanup_interrupt, probe_error in cases:
            with self.subTest(
                cleanup_error=type(cleanup_interrupt),
                probe_error=type(probe_error),
            ):
                plugin_id = f"probe-{type(probe_error).__name__.lower()}"
                self._plugin(plugin_id)

                class ProbeFailureRuntime(_CoordinatorRuntime):
                    def __init__(self, plugin_root, load_spec, broker):
                        self.probe_fails = False
                        super().__init__(plugin_root, load_spec, broker)

                    @property
                    def snapshot(self):
                        if self.probe_fails:
                            raise probe_error
                        return self._owned_snapshot

                    @snapshot.setter
                    def snapshot(self, value):
                        self._owned_snapshot = value

                    def invoke(self, action):
                        self.actions.append(action)
                        if action is LifecycleAction.CLEANUP:
                            self.probe_fails = True
                            raise cleanup_interrupt
                        statuses = {
                            LifecycleAction.LOAD: "loaded",
                            LifecycleAction.SHUTDOWN: "unloaded",
                        }
                        return SimpleNamespace(
                            success=True,
                            status=statuses[action],
                            error="",
                        )

                    def close(self):
                        self.closed = True

                loader = PluginLoader(
                    self.tmp.name,
                    self.broker,
                    runtime_factory=ProbeFailureRuntime,
                )
                manifest = next(
                    manifest
                    for manifest in loader.discover_plugins()
                    if manifest.plugin_id == plugin_id
                )
                instance = loader.load_plugin(manifest)

                with self.assertRaises(type(cleanup_interrupt)) as raised:
                    loader.unload_plugin(plugin_id)

                runtime = ProbeFailureRuntime.created[-1]
                self.assertIs(raised.exception, cleanup_interrupt)
                self.assertIn(LifecycleAction.SHUTDOWN, runtime.actions)
                self.assertTrue(runtime.closed)
                self.assertIs(loader.get_plugin(plugin_id), instance)
                self.assertEqual(instance.status, PluginStatus.ERROR)
                self.assertIs(instance._runtime, runtime)
                self.assertIn(
                    "PLUGIN_WORKER_TERMINATION_UNCONFIRMED",
                    instance.error_message,
                )

    def test_close_attempts_shutdown_for_every_worker_after_cleanup_failure(self):
        for plugin_id in ("close-one", "close-two"):
            self._plugin(plugin_id)

        class CleanupFailureRuntime(_CoordinatorRuntime):
            def invoke(self, action):
                if action is LifecycleAction.CLEANUP and self.plugin_root.name == "close-one":
                    self.actions.append(action)
                    raise RuntimeError("cleanup failed")
                return super().invoke(action)

        manager = PluginManager(
            self.tmp.name,
            event_bus=self.bus,
            grants={},
            runtime_factory=CleanupFailureRuntime,
        )
        for manifest in manager.discover():
            manager.load(manifest)

        manager.close()

        runtimes = CleanupFailureRuntime.created[-2:]
        self.assertEqual(len(runtimes), 2)
        self.assertTrue(all(LifecycleAction.SHUTDOWN in runtime.actions for runtime in runtimes))
        self.assertTrue(all(runtime.snapshot.termination_confirmed for runtime in runtimes))

    def test_manager_close_reaps_every_worker_then_rethrows_first_base_exception(self):
        for plugin_id in ("close-a", "close-b"):
            self._plugin(plugin_id)
        first_error = SystemExit("first cleanup interrupt")
        second_error = KeyboardInterrupt("second cleanup interrupt")

        class InterruptedCleanupRuntime(_CoordinatorRuntime):
            def invoke(self, action):
                if action is LifecycleAction.CLEANUP:
                    self.actions.append(action)
                    if self.plugin_root.name == "close-a":
                        raise first_error
                    raise second_error
                return super().invoke(action)

        manager = PluginManager(
            self.tmp.name,
            event_bus=self.bus,
            grants={},
            runtime_factory=InterruptedCleanupRuntime,
        )
        for manifest in manager.discover():
            manager.load(manifest)

        with self.assertRaises(SystemExit) as raised:
            manager.close()

        runtimes = InterruptedCleanupRuntime.created[-2:]
        self.assertIs(raised.exception, first_error)
        self.assertEqual(len(runtimes), 2)
        self.assertTrue(
            all(LifecycleAction.SHUTDOWN in runtime.actions for runtime in runtimes)
        )
        self.assertTrue(all(runtime.closed for runtime in runtimes))
        self.assertTrue(
            all(runtime.snapshot.termination_confirmed for runtime in runtimes)
        )
        self.assertTrue(
            all(manager.get_plugin(plugin_id) is None for plugin_id in ("close-a", "close-b"))
        )

    def test_close_shuts_workers_down_in_plugin_id_order(self):
        for plugin_id in ("close-z", "close-a"):
            self._plugin(plugin_id)

        class OrderedRuntime(_CoordinatorRuntime):
            shutdown_order = []

            def invoke(self, action):
                if action is LifecycleAction.SHUTDOWN:
                    type(self).shutdown_order.append(self.plugin_root.name)
                return super().invoke(action)

        manager = PluginManager(
            self.tmp.name,
            event_bus=self.bus,
            grants={},
            runtime_factory=OrderedRuntime,
        )
        manifests = manager.discover()
        for manifest in reversed(manifests):
            manager.load(manifest)

        manager.close()

        self.assertEqual(OrderedRuntime.shutdown_order, ["close-a", "close-z"])

    def test_cleanup_failure_is_reported_after_confirmed_shutdown(self):
        self._plugin("cleanup-failure")

        class CleanupResultFailureRuntime(_CoordinatorRuntime):
            def invoke(self, action):
                if action is LifecycleAction.CLEANUP:
                    self.actions.append(action)
                    return SimpleNamespace(
                        success=False,
                        status="error",
                        error="cleanup_failed",
                    )
                return super().invoke(action)

        loader = PluginLoader(
            self.tmp.name,
            self.broker,
            runtime_factory=CleanupResultFailureRuntime,
        )
        manifest = next(
            item for item in loader.discover_plugins()
            if item.plugin_id == "cleanup-failure"
        )
        instance = loader.load_plugin(manifest)
        runtime = CleanupResultFailureRuntime.created[-1]

        self.assertFalse(loader.unload_plugin("cleanup-failure"))
        self.assertEqual(instance.status, PluginStatus.UNLOADED)
        self.assertIn("PLUGIN_CLEANUP_FAILED", instance.error_message)
        self.assertIsNone(loader.get_plugin("cleanup-failure"))
        self.assertIn(LifecycleAction.SHUTDOWN, runtime.actions)
        self.assertTrue(runtime.snapshot.termination_confirmed)

    def test_linked_root_and_entrypoint_are_rejected(self):
        external = Path(self.tmp.name).parent / f"external-plugin-{os.getpid()}"
        external.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, external, True)
        (external / "manifest.json").write_text("{}", encoding="utf-8")
        linked_root = Path(self.tmp.name) / "linked-root"
        try:
            linked_root.symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        self.assertNotIn(
            "linked-root",
            {manifest.plugin_id for manifest in self.loader.discover_plugins()},
        )

        self._plugin("linked-entry")
        entrypoint = Path(self.tmp.name) / "linked-entry" / "plugin.py"
        entrypoint.unlink()
        entrypoint.symlink_to(external / "manifest.json")
        with self.assertRaises(ValueError):
            self.loader.load_plugin(self._manifest("linked-entry"))

    def test_windows_reparse_flag_is_treated_as_a_link(self):
        import core.kernel.plugin_sdk as plugin_sdk

        details = SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
        )
        with patch.object(Path, "lstat", return_value=details):
            self.assertTrue(plugin_sdk._is_link_or_reparse(Path("junction")))


class TestPluginManagerBrokerRegistration(unittest.TestCase):
    def test_plugin_manager_registers_read_only_system_stats_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(
                plugins_dir=tmp,
                grants={"stats-plugin": {"system.stats"}},
            )
            try:
                session = manager.broker.begin_lifecycle(
                    "stats-plugin", "request-1", ("system_monitor",), generation=1
                )
                allowed = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-1",
                        plugin_id="stats-plugin",
                        capability="system.stats",
                        arguments={},
                    )
                )
            finally:
                manager.close()
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")
        for group in ("cpu", "memory", "disk", "network", "process"):
            self.assertIn(group, allowed.result)

    def test_plugin_manager_registers_file_read_handler_inside_plugins_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("plugin-config", encoding="utf-8")
            manager = PluginManager(
                plugins_dir=tmp,
                grants={"reader-plugin": {"file.read"}},
            )
            try:
                manager.broker.bind_file_read_root("reader-plugin", root)
                session = manager.broker.begin_lifecycle(
                    "reader-plugin", "request-1", ("file_read",), generation=1
                )
                allowed = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-1",
                        plugin_id="reader-plugin",
                        capability="file.read",
                        arguments={"path": "note.txt"},
                    )
                )
            finally:
                manager.close()
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")
        self.assertEqual(allowed.result, "plugin-config")

    def test_plugin_manager_registers_file_list_handler_inside_plugins_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "note.txt").write_text("plugin-config", encoding="utf-8")
            manager = PluginManager(
                plugins_dir=tmp,
                grants={"reader-plugin": {"file.list"}},
            )
            try:
                manager.broker.bind_file_read_root("reader-plugin", root)
                session = manager.broker.begin_lifecycle(
                    "reader-plugin", "request-1", ("file_read",), generation=1
                )
                allowed = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-1",
                        plugin_id="reader-plugin",
                        capability="file.list",
                        arguments={"path": "."},
                    )
                )
            finally:
                manager.close()
        self.assertTrue(allowed.allowed)
        self.assertEqual(
            allowed.result,
            ({"name": "note.txt", "type": "file"},),
        )

    def test_default_first_party_grants_do_not_include_system_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(plugins_dir=tmp)
            try:
                session = manager.broker.begin_lifecycle(
                    "event-logger", "request-2", ("system_monitor",), generation=1
                )
                denied = session.handle(
                    PluginBrokerRequest(
                        request_id="request-2",
                        call_id="call-1",
                        plugin_id="event-logger",
                        capability="system.stats",
                        arguments={},
                    )
                )
            finally:
                manager.close()
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_granted")

    def test_default_first_party_grants_do_not_include_file_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(plugins_dir=tmp)
            try:
                session = manager.broker.begin_lifecycle(
                    "event-logger", "request-2", ("file_read",), generation=1
                )
                denied = session.handle(
                    PluginBrokerRequest(
                        request_id="request-2",
                        call_id="call-1",
                        plugin_id="event-logger",
                        capability="file.read",
                        arguments={"path": "note.txt"},
                    )
                )
            finally:
                manager.close()
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_granted")

    def test_default_first_party_grants_do_not_include_file_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(plugins_dir=tmp)
            try:
                session = manager.broker.begin_lifecycle(
                    "event-logger", "request-2", ("file_read",), generation=1
                )
                denied = session.handle(
                    PluginBrokerRequest(
                        request_id="request-2",
                        call_id="call-1",
                        plugin_id="event-logger",
                        capability="file.list",
                        arguments={"path": "."},
                    )
                )
            finally:
                manager.close()
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_granted")



    def test_plugin_manager_registers_config_get_handler_inside_plugins_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text(
                '{"theme": "dark"}', encoding="utf-8"
            )
            manager = PluginManager(
                plugins_dir=tmp,
                grants={"config-plugin": {"config.get"}},
            )
            try:
                manager.broker.bind_file_read_root("config-plugin", root)
                session = manager.broker.begin_lifecycle(
                    "config-plugin", "request-1", ("system_config",), generation=1
                )
                allowed = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-1",
                        plugin_id="config-plugin",
                        capability="config.get",
                        arguments={"key": "theme", "default": "light"},
                    )
                )
            finally:
                manager.close()
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")
        self.assertEqual(allowed.result, "dark")

    def test_default_first_party_grants_do_not_include_config_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(plugins_dir=tmp)
            try:
                session = manager.broker.begin_lifecycle(
                    "event-logger", "request-2", ("system_config",), generation=1
                )
                denied = session.handle(
                    PluginBrokerRequest(
                        request_id="request-2",
                        call_id="call-1",
                        plugin_id="event-logger",
                        capability="config.get",
                        arguments={"key": "theme", "default": "light"},
                    )
                )
            finally:
                manager.close()
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_granted")





    def test_plugin_manager_registers_llm_call_handler_when_provider_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(
                plugins_dir=tmp,
                grants={"llm-plugin": {"llm.call"}},
            )
            try:
                session = manager.broker.begin_lifecycle(
                    "llm-plugin", "request-1", ("llm_access",), generation=1
                )
                unregistered = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-1",
                        plugin_id="llm-plugin",
                        capability="llm.call",
                        arguments={"prompt": "hello", "model": "llama3"},
                    )
                )
                self.assertEqual(unregistered.error, "capability_not_registered")

                manager.broker.register_llm_call_handler(
                    lambda prompt, model: {"reply": f"{model}:{prompt}"}
                )
                allowed = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-2",
                        plugin_id="llm-plugin",
                        capability="llm.call",
                        arguments={"prompt": "hello", "model": "llama3"},
                    )
                )
            finally:
                manager.close()
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.error, "")
        self.assertEqual(allowed.result, {"reply": "llama3:hello"})

    def test_default_first_party_grants_do_not_include_llm_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(plugins_dir=tmp)
            try:
                session = manager.broker.begin_lifecycle(
                    "event-logger", "request-2", ("llm_access",), generation=1
                )
                denied = session.handle(
                    PluginBrokerRequest(
                        request_id="request-2",
                        call_id="call-1",
                        plugin_id="event-logger",
                        capability="llm.call",
                        arguments={"prompt": "hello", "model": "llama3"},
                    )
                )
            finally:
                manager.close()
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_granted")

    def test_plugin_manager_registers_network_get_handler_when_hosts_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(
                plugins_dir=tmp,
                grants={"net-plugin": {"network.get"}},
            )
            try:
                session = manager.broker.begin_lifecycle(
                    "net-plugin", "request-1", ("network",), generation=1
                )
                unregistered = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-1",
                        plugin_id="net-plugin",
                        capability="network.get",
                        arguments={"url": "http://127.0.0.1/blocked"},
                    )
                )
                self.assertEqual(
                    unregistered.error, "capability_not_registered"
                )

                manager.broker.register_network_get_handler(["example.com"])
                denied = session.handle(
                    PluginBrokerRequest(
                        request_id="request-1",
                        call_id="call-2",
                        plugin_id="net-plugin",
                        capability="network.get",
                        arguments={"url": "http://127.0.0.1/blocked"},
                    )
                )
            finally:
                manager.close()
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "network_get_denied")

    def test_default_first_party_grants_do_not_include_network_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(plugins_dir=tmp)
            try:
                session = manager.broker.begin_lifecycle(
                    "event-logger", "request-3", ("network",), generation=1
                )
                denied = session.handle(
                    PluginBrokerRequest(
                        request_id="request-3",
                        call_id="call-1",
                        plugin_id="event-logger",
                        capability="network.get",
                        arguments={"url": "http://127.0.0.1/blocked"},
                    )
                )
            finally:
                manager.close()
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "capability_not_granted")


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
               TestPluginSandboxPolicy, TestPluginWorkerCoordinator,
               TestPluginManagerBrokerRegistration]:
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
