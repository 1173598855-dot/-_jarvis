"""Static guardrails for the repository GitHub Actions workflow."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class TestCiWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    @classmethod
    def _job_block(cls, name: str) -> str:
        marker = f"  {name}:\n"
        start = cls.text.index(marker)
        remainder = cls.text[start + len(marker) :]
        next_job = re.search(r"\n  [A-Za-z0-9_-]+:\n", remainder)
        end = len(remainder) if next_job is None else next_job.start()
        return marker + remainder[:end]

    def test_python_jobs_install_the_hash_lock_and_editable_project(self):
        self.assertIn("actions/setup-node@v4", self.text)
        locked_install = "python -m pip install --require-hashes -r requirements.lock"

        self.assertGreaterEqual(self.text.count(locked_install), 2)
        self.assertIn(
            "python -m pip install --no-deps --no-build-isolation -e .",
            self.text,
        )
        self.assertNotIn("python -m pip install ruff", self.text)
        self.assertNotIn('python -m pip install -e ".[dev]"', self.text)
        self.assertIn("python -m ruff check src/ tests/ scripts/", self.text)
        self.assertIn("python tests/run_all.py", self.text)
        # Discovery runs through the bounded wrapper so a wedged test is named
        # instead of silently consuming the job-level cap.
        self.assertIn(
            "python scripts/discover_tests.py --timeout 1800",
            self.text,
        )
        self.assertNotIn('python -m unittest discover -s tests -p "test_*.py"', self.text)
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

    def test_linux_sandbox_job_runs_the_opt_in_real_enforcement_probe(self):
        job = self._job_block("linux-sandbox")
        command = (
            "      - run: python -m unittest "
            "tests.test_worker_network_isolation "
            "tests.test_worker_filesystem_isolation "
            "tests.test_linux_worker_isolation_enforcement "
            "tests.test_linux_plugin_runtime_enforcement "
            "tests.test_linux_terminal_worker_enforcement -v\n"
            "        env:\n"
            '          JARVIS_RUN_LINUX_ISOLATION_ENFORCEMENT: "1"\n'
            '          JARVIS_RUN_LINUX_PLUGIN_RUNTIME_ENFORCEMENT: "1"\n'
            '          JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT: "1"'
        )

        self.assertIn("runs-on: ubuntu-22.04", job)
        self.assertIn(
            command,
            job,
        )

    def test_python_contract_job_runs_required_local_integration_profile(self):
        self.assertIn("python scripts/ci_local_integration.py --require-services", self.text)
        # The integration step carries its own deadline; the job cap is a backstop.
        self.assertIn("--overall-timeout 900", self.text)
        self.assertIn("local_ollama_fixture.py", self.text)
