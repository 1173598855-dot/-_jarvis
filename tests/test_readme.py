"""README quality guardrails."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent


class TestReadme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_readme_links_setup_documentation(self):
        self.assertIn("docs/SETUP.md", self.text)
        self.assertIn("Developer Setup", self.text)

    def test_readme_uses_the_hash_checked_python_lock(self):
        self.assertIn("requirements.lock", self.text)
        self.assertIn("pip install --require-hashes -r requirements.lock", self.text)
        self.assertIn("pip install --no-deps --no-build-isolation -e .", self.text)

    def test_reports_have_one_canonical_home(self):
        self.assertIn("docs/reports/README.md", self.text)
        reports = ROOT / "docs" / "reports"
        producers = [
            ROOT / "skills" / "github-learner" / "SKILL.md",
            ROOT / "docs" / "protocols" / "JARVIS_核心指令.md",
        ]

        self.assertTrue((reports / "PROJECT_ANALYSIS.md").is_file())
        self.assertTrue((reports / "GITHUB_LEARNING_REPORT.md").is_file())
        self.assertFalse((ROOT / "PROJECT_ANALYSIS.md").exists())
        self.assertFalse((ROOT / "GITHUB_LEARNING_REPORT.md").exists())
        for producer in producers:
            producer_text = producer.read_text(encoding="utf-8")
            self.assertIn("docs/reports/GITHUB_LEARNING_REPORT.md", producer_text)
            self.assertNotRegex(
                producer_text,
                r"(?<!docs/reports/)GITHUB_LEARNING_REPORT\.md",
            )

    def test_readme_links_shared_api_contract(self):
        self.assertIn("contracts/core-api.openapi.json", self.text)

    def test_readme_describes_main_services(self):
        self.assertIn("Python HTTPServer", self.text)
        self.assertIn("FastAPI", self.text)
        self.assertIn("Express", self.text)
        self.assertIn("Solid.js", self.text)

    def test_readme_documents_worker_isolated_plugin_runtime(self):
        self.assertIn("python_worker", self.text)
        self.assertIn("event.emit", self.text)
        self.assertIn("same-user", self.text)
        self.assertIn("PluginManager", self.text)

    def test_readme_has_no_mojibake_markers(self):
        markers = ["鈹", "鐢", "绔", "鍚", "馃", "�", "鏍", "璐", "淮"]
        found = [marker for marker in markers if marker in self.text]
        self.assertEqual(found, [])


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestReadme)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
