"""Plugin installation, discovery, and real Worker lifecycle guardrails."""

from __future__ import annotations

# Direct-script test bootstrap must precede project-local imports.
# ruff: noqa: E402
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core.kernel.event_bus import EventBus
from core.kernel.plugin_sdk import PluginManager, PluginStatus


class TestPluginInstallation(unittest.TestCase):
    def setUp(self):
        self._managers: list[PluginManager] = []

    def tearDown(self):
        for manager in reversed(self._managers):
            manager.close()

    def _manager(self, plugins_dir=ROOT / "plugins", *, event_bus=None, grants=None):
        kwargs = {"event_bus": event_bus or EventBus()}
        if grants is not None:
            kwargs["grants"] = grants
        manager = PluginManager(plugins_dir, **kwargs)
        self._managers.append(manager)
        return manager

    @staticmethod
    def _manifest(manager, plugin_id):
        return next(
            manifest
            for manifest in manager.discover()
            if manifest.plugin_id == plugin_id
        )

    def test_repository_plugins_are_discoverable_as_workers(self):
        manager = self._manager()
        manifests = {manifest.plugin_id: manifest for manifest in manager.discover()}

        self.assertEqual(
            {manifests[plugin_id].runtime for plugin_id in ("plugin-template", "event-logger")},
            {"python_worker"},
        )

    def test_first_party_plugin_runs_in_distinct_pid_and_emits_parent_owned_event(self):
        bus = EventBus()
        manager = self._manager(event_bus=bus)
        instance = manager.load(self._manifest(manager, "event-logger"))

        self.assertGreater(instance.worker_pid, 0)
        self.assertNotEqual(instance.worker_pid, os.getpid())
        self.assertTrue(manager.enable("event-logger"))
        event = bus.get_history()[-1]
        self.assertEqual(event.event_type, "plugin.activated")
        self.assertEqual(event.source, "plugin:event-logger")
        self.assertEqual(event.data, {"plugin_id": "event-logger"})
        manager.close()
        self.assertEqual(instance.worker_pid, 0)

    def test_plugin_template_real_worker_lifecycle(self):
        bus = EventBus()
        manager = self._manager(event_bus=bus)
        instance = manager.load(self._manifest(manager, "plugin-template"))

        self.assertEqual(instance.status, PluginStatus.LOADED)
        self.assertGreater(instance.worker_pid, 0)
        self.assertNotEqual(instance.worker_pid, os.getpid())
        self.assertTrue(manager.enable("plugin-template"))
        self.assertEqual(instance.status, PluginStatus.ENABLED)
        self.assertTrue(manager.disable("plugin-template"))
        self.assertEqual(instance.status, PluginStatus.DISABLED)
        manager.close()
        self.assertEqual(instance.status, PluginStatus.UNLOADED)
        self.assertEqual(instance.worker_pid, 0)
        self.assertIsNone(manager.get_plugin("plugin-template"))

    def test_first_party_plugins_never_enter_parent_module_cache(self):
        roots = [(ROOT / "plugins" / plugin_id).resolve() for plugin_id in ("event-logger", "plugin-template")]
        manager = self._manager()
        for plugin_id in ("event-logger", "plugin-template"):
            manager.load(self._manifest(manager, plugin_id))

        parent_plugin_modules = []
        for module in tuple(sys.modules.values()):
            raw_file = getattr(module, "__file__", None)
            if not raw_file:
                continue
            try:
                module_path = Path(raw_file).resolve()
            except (OSError, RuntimeError):
                continue
            if any(module_path == root or root in module_path.parents for root in roots):
                parent_plugin_modules.append(module_path)
        self.assertEqual(parent_plugin_modules, [])

    def test_import_failure_is_bounded_error_instance_and_worker_is_reaped(self):
        with tempfile.TemporaryDirectory(prefix="plugin_import_failure_") as tmp:
            root = Path(tmp) / "broken-plugin"
            root.mkdir()
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "name": "broken-plugin",
                        "version": "1.0.0",
                        "description": "broken import",
                        "permissions": [],
                        "runtime": "python_worker",
                        "entry_point": "plugin.py",
                        "plugin_id": "broken-plugin",
                    }
                ),
                encoding="utf-8",
            )
            (root / "plugin.py").write_text(
                "raise ImportError('token=' + 's' * 5000)\n",
                encoding="utf-8",
            )
            manager = self._manager(tmp, grants={})

            instance = manager.load(self._manifest(manager, "broken-plugin"))

            self.assertEqual(instance.status, PluginStatus.ERROR)
            self.assertLessEqual(len(instance.error_message), 512)
            self.assertNotIn("s" * 100, instance.error_message)
            self.assertEqual(instance.worker_pid, 0)

    def test_disable_without_plugin_hook_is_successful(self):
        with tempfile.TemporaryDirectory(prefix="plugin_no_deactivate_") as tmp:
            root = Path(tmp) / "no-deactivate"
            root.mkdir()
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "name": "no-deactivate",
                        "version": "1.0.0",
                        "description": "no deactivate hook",
                        "permissions": [],
                        "runtime": "python_worker",
                        "entry_point": "plugin.py",
                        "plugin_id": "no-deactivate",
                    }
                ),
                encoding="utf-8",
            )
            (root / "plugin.py").write_text(
                "def activate(api):\n    pass\n",
                encoding="utf-8",
            )
            manager = self._manager(tmp, grants={})
            instance = manager.load(self._manifest(manager, "no-deactivate"))

            self.assertTrue(manager.enable("no-deactivate"))
            self.assertTrue(manager.disable("no-deactivate"))
            self.assertEqual(instance.status, PluginStatus.DISABLED)
            manager.close()

    def test_unload_missing_returns_false(self):
        self.assertFalse(self._manager().unload("missing"))

    def test_readme_documents_plugin_setup(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("plugins/", readme)
        self.assertIn("manifest.json", readme)
        self.assertIn("plugin-template", readme)


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPluginInstallation)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
