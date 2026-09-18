"""Project configuration tests."""

import sys
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by Python 3.10
    import tomli as tomllib

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

    def test_ruff_linter_dependency_declared(self):
        dev_deps = self._dependency_names(
            self.config["project"]["optional-dependencies"]["dev"]
        )
        self.assertIn("ruff", dev_deps)

    def test_python_310_toml_backport_dependency_declared(self):
        dev_dependencies = self.config["project"]["optional-dependencies"]["dev"]

        self.assertIn(
            "tomli>=2.0.0; python_version < '3.11'",
            dev_dependencies,
        )


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPythonDependencies)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
