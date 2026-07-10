"""
Plugin installation and discovery guardrails.
"""
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


class TestPluginInstallation(unittest.TestCase):
    def test_plugin_template_is_discoverable(self):
        from core.kernel.plugin_sdk import PluginLoader

        loader = PluginLoader(plugins_dir=str(ROOT / "plugins"))
        manifests = loader.discover_plugins()
        plugin_ids = [manifest.plugin_id for manifest in manifests]
        self.assertIn("plugin-template", plugin_ids)

    def test_event_logger_is_discoverable(self):
        from core.kernel.plugin_sdk import PluginLoader

        loader = PluginLoader(plugins_dir=str(ROOT / "plugins"))
        manifests = loader.discover_plugins()
        plugin_ids = [manifest.plugin_id for manifest in manifests]
        self.assertIn("event-logger", plugin_ids)

    def test_plugin_template_can_load(self):
        from core.kernel.plugin_sdk import PluginLoader

        loader = PluginLoader(plugins_dir=str(ROOT / "plugins"))
        manifest = next(manifest for manifest in loader.discover_plugins() if manifest.plugin_id == "plugin-template")
        instance = loader.load_plugin(manifest)
        self.assertEqual(instance.status.value, "loaded")

    def test_readme_documents_plugin_setup(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("plugins/", readme)
        self.assertIn("manifest.json", readme)
        self.assertIn("plugin-template", readme)

    def test_plugin_template_lifecycle(self):
        from core.kernel.plugin_sdk import PluginLoader, PluginStatus

        loader = PluginLoader(plugins_dir=str(ROOT / "plugins"))
        manifest = next(manifest for manifest in loader.discover_plugins() if manifest.plugin_id == "plugin-template")
        instance = loader.load_plugin(manifest)
        self.assertEqual(instance.status, PluginStatus.LOADED)

        self.assertTrue(loader.enable_plugin(manifest.plugin_id))
        self.assertEqual(loader.get_plugin(manifest.plugin_id).status, PluginStatus.ENABLED)

        self.assertTrue(loader.disable_plugin(manifest.plugin_id))
        self.assertEqual(loader.get_plugin(manifest.plugin_id).status, PluginStatus.DISABLED)

        self.assertTrue(loader.unload_plugin(manifest.plugin_id))
        self.assertIsNone(loader.get_plugin(manifest.plugin_id))

    def test_event_logger_lifecycle(self):
        from core.kernel.plugin_sdk import PluginLoader, PluginStatus

        loader = PluginLoader(plugins_dir=str(ROOT / "plugins"))
        manifest = next(manifest for manifest in loader.discover_plugins() if manifest.plugin_id == "event-logger")
        instance = loader.load_plugin(manifest)
        self.assertEqual(instance.status, PluginStatus.LOADED)

        self.assertTrue(loader.enable_plugin(manifest.plugin_id))
        self.assertEqual(loader.get_plugin(manifest.plugin_id).status, PluginStatus.ENABLED)

        self.assertTrue(loader.disable_plugin(manifest.plugin_id))
        self.assertEqual(loader.get_plugin(manifest.plugin_id).status, PluginStatus.DISABLED)

        self.assertTrue(loader.unload_plugin(manifest.plugin_id))
        self.assertIsNone(loader.get_plugin(manifest.plugin_id))


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPluginInstallation)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
