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

    def test_readme_links_report_index(self):
        self.assertIn("docs/reports/README.md", self.text)

    def test_readme_links_shared_api_contract(self):
        self.assertIn("contracts/core-api.openapi.json", self.text)

    def test_readme_describes_main_services(self):
        self.assertIn("Python HTTPServer", self.text)
        self.assertIn("FastAPI", self.text)
        self.assertIn("Express", self.text)
        self.assertIn("Solid.js", self.text)

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
