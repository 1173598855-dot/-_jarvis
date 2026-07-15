"""Static guardrails for the repository GitHub Actions workflow."""

import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class TestCiWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_python_contract_job_installs_runtime_and_node_dependencies(self):
        self.assertIn("actions/setup-node@v4", self.text)
        self.assertIn('python -m pip install -e ".[dev]"', self.text)
        self.assertIn("python tests/run_all.py", self.text)
        self.assertIn('python -m unittest discover -s tests -p "test_*.py"', self.text)
        self.assertIn("python -m compileall -q src tests scripts", self.text)

    def test_frontend_job_runs_unit_browser_type_and_build_checks(self):
        self.assertIn("npm ci", self.text)
        self.assertIn("npx playwright install --with-deps chromium", self.text)
        self.assertIn("npm test -- --run", self.text)
        self.assertIn("npm run test:e2e", self.text)
        self.assertIn("npm run typecheck", self.text)
        self.assertIn("npm run build", self.text)

    def test_workflow_does_not_ignore_verification_failures(self):
        self.assertNotIn("|| true", self.text)

    def test_python_contract_job_runs_required_local_integration_profile(self):
        self.assertIn("python scripts/ci_local_integration.py --require-services", self.text)
        self.assertIn("local_ollama_fixture.py", self.text)
