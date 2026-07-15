"""Guardrails for the deterministic CI local-integration runner."""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent
RUNNER = ROOT / "scripts" / "ci_local_integration.py"
FIXTURE = ROOT / "scripts" / "local_ollama_fixture.py"


class TestLocalIntegrationRunner(unittest.TestCase):
    def test_runner_and_fixture_are_repository_owned(self):
        self.assertTrue(RUNNER.is_file())
        self.assertTrue(FIXTURE.is_file())

    def test_runner_exposes_required_services_mode(self):
        spec = importlib.util.spec_from_file_location("jarvis_ci_runner", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertIn("--require-services", module.build_parser().format_help())
        self.assertTrue(callable(module.run_integration))

    def test_fixture_declares_minimal_ollama_contract(self):
        text = FIXTURE.read_text(encoding="utf-8")
        for path in ("/api/version", "/api/tags", "/api/chat"):
            self.assertIn(path, text)
        self.assertIn('"prompt_eval_count"', text)
        self.assertIn('"eval_count"', text)


if __name__ == "__main__":
    unittest.main()
