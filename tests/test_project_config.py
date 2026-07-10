"""Project configuration tests."""

import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent


class TestPythonDependencies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "pyproject.toml").open("rb") as f:
            cls.config = tomllib.load(f)

    def _dependency_names(self, values):
        names = set()
        for value in values:
            name = value.split(";", 1)[0].split("[", 1)[0]
            for marker in ("==", ">=", "<=", "~=", "!=", ">", "<"):
                name = name.split(marker, 1)[0]
            names.add(name.strip().lower())
        return names

    def test_fastapi_runtime_dependencies_declared(self):
        deps = self._dependency_names(self.config["project"]["dependencies"])
        self.assertIn("fastapi", deps)
        self.assertIn("uvicorn", deps)

    def test_fastapi_testclient_dependency_declared(self):
        dev_deps = self._dependency_names(
            self.config["project"]["optional-dependencies"]["dev"]
        )
        self.assertIn("httpx2", dev_deps)


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPythonDependencies)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
