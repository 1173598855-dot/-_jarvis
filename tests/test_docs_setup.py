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


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestSetupDocs)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
