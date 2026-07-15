"""Guardrails for the aggregate test runner."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import run_all
import tempfile


class TestRunAllCoverage(unittest.TestCase):
    def test_run_suite_has_no_statements_after_final_return(self):
        import ast
        import inspect

        function = ast.parse(inspect.getsource(run_all._run_suite)).body[0]
        final_return = min(
            index
            for index, statement in enumerate(function.body)
            if isinstance(statement, ast.Return)
        )

        self.assertEqual(final_return, len(function.body) - 1)

    def test_run_all_tests_reports_timeout_when_exceeded(self):
        report = run_all.ROOT / ".test-run-all-timeout-report.json"
        if report.exists():
            report.unlink()

        slow_case = type("SlowCase", (unittest.TestCase,), {
            "test_slow": lambda self: __import__("time").sleep(2)
        })
        original_cases = run_all.AGGREGATE_TEST_CASES[:]
        run_all.AGGREGATE_TEST_CASES[:] = [slow_case]
        try:
            self.assertEqual(run_all.run_all_tests(timeout=1, json_report=str(report)), 1)
        finally:
            run_all.AGGREGATE_TEST_CASES[:] = original_cases

        payload = __import__("json").loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["success"], False)
        self.assertEqual(payload["timeout_expired"], True)
        self.assertEqual(payload["timeout_seconds"], 1)

        report.unlink()

    def test_run_all_tests_accepts_timeout_and_writes_json_report(self):
        report = Path(__file__).parent.parent / ".test-run-all-report.json"
        if report.exists():
            report.unlink()

        timeout = 60
        self.assertEqual(run_all.run_all_tests(timeout=timeout, json_report=str(report)), 0)

        payload = __import__("json").loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["tests"], run_all.canonical_test_count())
        self.assertEqual(payload["success"], True)
        self.assertEqual(payload["timeout_seconds"], timeout)
        self.assertIn(f"{run_all.canonical_test_count()} tests", payload["title"])

        report.unlink()


    def test_run_smoke_tests_runs_subset_and_writes_report(self):
        report = Path(__file__).parent.parent / ".test-smoke-report.json"
        if report.exists():
            report.unlink()

        timeout = 15
        self.assertEqual(run_all.run_smoke_tests(timeout=timeout, json_report=str(report)), 0)

        payload = __import__("json").loads(report.read_text(encoding="utf-8"))
        smoke_count = run_all.build_smoke_suite().countTestCases()
        self.assertEqual(payload["success"], True)
        self.assertIn(f"{smoke_count} tests", payload["title"])
        self.assertEqual(payload["timeout_seconds"], timeout)

        report.unlink()

    def test_aggregate_runner_includes_documentation_and_config_guards(self):
        case_names = {case.__name__ for case in run_all.AGGREGATE_TEST_CASES}

        self.assertIn("TestReadme", case_names)
        self.assertIn("TestSetupDocs", case_names)
        self.assertIn("TestPythonDependencies", case_names)
        self.assertIn("TestIterationLedger", case_names)
        self.assertIn("TestSharedApiContract", case_names)
        self.assertIn("TestLocalIntegrationProfile", case_names)
        self.assertIn("TestRequestBodyLimitMiddleware", case_names)

    def test_build_aggregate_suite_loads_every_declared_case(self):
        expected = sum(
            unittest.defaultTestLoader.loadTestsFromTestCase(case).countTestCases()
            for case in run_all.AGGREGATE_TEST_CASES
        )

        suite = run_all.build_aggregate_suite()

        self.assertEqual(suite.countTestCases(), expected)

    def test_aggregate_suite_title_uses_declared_case_count(self):
        title = run_all.aggregate_suite_title()

        self.assertIn(f"({len(run_all.AGGREGATE_TEST_CASES)} classes)", title)


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestRunAllCoverage)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
