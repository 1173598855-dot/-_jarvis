"""Documentation guardrails for setup instructions."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent


class TestSetupDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")

    def test_documents_python_dev_install(self):
        self.assertIn('pip install -e ".[dev]"', self.text)

    def test_documents_httpx2_test_dependency(self):
        self.assertIn("`httpx2`", self.text)

    def test_documents_cors_environment_variable(self):
        self.assertIn("JARVIS_ALLOWED_ORIGINS", self.text)
        self.assertIn("Access-Control-Allow-Origin", self.text)

    def test_documents_frontend_verification(self):
        self.assertIn("npm test -- server.test.js", self.text)
        self.assertIn("npm run typecheck", self.text)
        self.assertIn("npm run build", self.text)

    def test_documents_optional_local_integration_profile(self):
        self.assertIn("scripts/local_integration_profile.py", self.text)
        self.assertIn("--require-services", self.text)

    def test_documents_deterministic_ci_local_integration(self):
        self.assertIn("scripts/ci_local_integration.py", self.text)
        self.assertIn("local Ollama fixture", self.text)

    def test_development_guide_documents_worker_plugin_runtime(self):
        guide = (ROOT / "docs" / "DEVELOPMENT_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("python_worker", guide)
        self.assertIn("event.emit", guide)
        self.assertIn("same-user", guide)

    def test_development_guide_names_worker_runtime_boundaries(self):
        guide = (ROOT / "docs" / "DEVELOPMENT_GUIDE.md").read_text(encoding="utf-8")
        for module_path in (
            "src/core/contracts/plugin_worker_protocol.py",
            "src/core/kernel/plugin_broker.py",
            "src/runtime/plugin_worker.py",
            "src/adapters/subprocess_plugin_runtime.py",
        ):
            self.assertIn(module_path, guide)


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestSetupDocs)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
