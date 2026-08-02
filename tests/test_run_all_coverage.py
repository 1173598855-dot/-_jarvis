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
        self.assertEqual(payload["skipped"], 0)

        report.unlink()

    def test_run_suite_reports_skipped_tests_separately(self):
        report = run_all.ROOT / ".test-run-all-skipped-report.json"
        if report.exists():
            report.unlink()

        class SkippedCase(unittest.TestCase):
            @unittest.skip("platform fixture")
            def test_skipped(self):
                pass

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SkippedCase)
        self.assertEqual(run_all._run_suite(suite, json_report=str(report)), 0)

        payload = __import__("json").loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["tests"], 1)
        self.assertEqual(payload["passed"], 0)
        self.assertEqual(payload["skipped"], 1)

        report.unlink()

    def test_run_all_tests_accepts_timeout_and_writes_json_report(self):
        report = Path(__file__).parent.parent / ".test-run-all-report.json"
        if report.exists():
            report.unlink()

        class PassingCase(unittest.TestCase):
            def test_passes(self):
                pass

        class SkippedCase(unittest.TestCase):
            @unittest.skip("injected skip")
            def test_skips(self):
                pass

        original_cases = run_all.AGGREGATE_TEST_CASES[:]
        run_all.AGGREGATE_TEST_CASES[:] = [PassingCase, SkippedCase]
        timeout = 5
        try:
            self.assertEqual(
                run_all.run_all_tests(
                    timeout=timeout,
                    json_report=str(report),
                ),
                0,
            )
        finally:
            run_all.AGGREGATE_TEST_CASES[:] = original_cases

        payload = __import__("json").loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["tests"], 2)
        self.assertEqual(payload["passed"], 1)
        self.assertEqual(payload["skipped"], 1)
        self.assertEqual(payload["success"], True)
        self.assertEqual(payload["timeout_seconds"], timeout)
        self.assertEqual(
            payload["title"],
            "J.A.R.V.I.S. test suite - TestSuite (2 tests)",
        )

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

    def test_aggregate_runner_includes_phase_a_recovery_guards(self):
        case_names = {case.__name__ for case in run_all.AGGREGATE_TEST_CASES}
        expected = {
            "TestRunState",
            "TestContextBudgetMonitor",
            "TestResumeDocument",
            "TestFileRunStateRepository",
            "TestRunLifecycleCoordinator",
            "TestGitWorkspaceInspector",
            "TestRunRecoveryLifespan",
            "TestPhaseARecoveryGate",
        }

        self.assertLessEqual(expected, case_names)

    def test_aggregate_runner_includes_role_worker_lifecycle_guards(self):
        case_names = {case.__name__ for case in run_all.AGGREGATE_TEST_CASES}
        expected = {
            "TestWorkerProtocol",
            "TestRoleWorkerSupervisor",
            "TestRoleTaskLifecycleEndpoints",
        }

        self.assertLessEqual(expected, case_names)

    def test_aggregate_runner_includes_plugin_worker_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = ("test_plugin_worker_protocol", "TestPluginWorkerProtocol")

        self.assertIn(expected, case_ids)
        self.assertEqual(case_ids.count(expected), 1)

    def test_aggregate_runner_includes_plugin_broker_guard_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = ("test_plugin_broker", "TestPluginBroker")

        self.assertIn(expected, case_ids)
        self.assertEqual(case_ids.count(expected), 1)

    def test_aggregate_runner_includes_plugin_sdk_worker_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = {
            ("test_plugin_sdk", "TestWorkerPluginLifecycle"),
            ("test_plugin_sdk_extended_v2", "TestWorkerCoordinatorGuards"),
        }

        self.assertLessEqual(expected, set(case_ids))
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_synchronous_role_dispatch_guards(self):
        case_names = {case.__name__ for case in run_all.AGGREGATE_TEST_CASES}
        expected = {
            "TestRoleDispatchServiceSelectionAndMapping",
            "TestRoleDispatchServiceLeases",
            "TestRoleDispatchServiceLockOrder",
            "TestRoleDispatchServiceBatch",
            "TestRoleDispatchEndpoints",
            "TestMainHTTPRoleDispatchWorkerAdapter",
            "TestMainHTTPStateLifecycle",
        }

        self.assertLessEqual(expected, case_names)

    def test_aggregate_runner_includes_controlled_role_tool_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = {
            ("test_agent_factory", "TestOllamaRoleExecution"),
            ("test_context_compressor", "TestMemoryStore"),
            ("test_ollama_manager", "TestChat"),
            ("test_ollama_manager_extended", "TestOllamaManagerChat"),
            ("test_read_only_role_tools", "TestReadOnlyRoleTools"),
            ("test_role_tool_loop", "TestRoleToolLoop"),
            ("test_role_tool_protocol", "TestRoleToolProtocol"),
            ("test_role_tools", "TestRoleToolBroker"),
            ("test_secret_redaction", "TestSecretRedaction"),
        }

        self.assertLessEqual(expected, set(case_ids))
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_capability_registry_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = {
            ("test_capability_registry", "TestCapabilityRecord"),
            ("test_capability_registry", "TestCapabilityRegistry"),
        }

        self.assertLessEqual(expected, set(case_ids))
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_capability_resolver_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = {
            ("test_capability_resolver", "TestCompatibilityEvaluation"),
            ("test_capability_resolver", "TestCapabilityQuery"),
            ("test_capability_resolver", "TestCapabilityResolver"),
        }

        self.assertLessEqual(expected, set(case_ids))
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_capability_store_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = {
            ("test_file_capability_store", "TestCapabilityPackageLimits"),
            ("test_file_capability_store", "TestCapabilityPackageRejection"),
            ("test_file_capability_store", "TestFileCapabilityStore"),
        }

        self.assertLessEqual(expected, set(case_ids))
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_build_aggregate_suite_loads_every_declared_case(self):
        expected = sum(
            unittest.defaultTestLoader.loadTestsFromTestCase(case).countTestCases()
            for case in run_all.AGGREGATE_TEST_CASES
        )

        suite = run_all.build_aggregate_suite()

        self.assertEqual(suite.countTestCases(), expected)

    def test_aggregate_suite_title_uses_declared_case_count(self):
        title = run_all.aggregate_suite_title()

        self.assertIn("Iteration 141", title)
        self.assertIn(f"({len(run_all.AGGREGATE_TEST_CASES)} classes)", title)


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestRunAllCoverage)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
