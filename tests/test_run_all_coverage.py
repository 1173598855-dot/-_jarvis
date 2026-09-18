"""Guardrails for the aggregate test runner."""

# Aggregate-runner bootstrap must precede importing the local run_all module.
# ruff: noqa: E402

import importlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))


import run_all


class TestMemoryEndpointTestIsolation(unittest.TestCase):
    """Memory endpoint regressions must never write through live app state."""

    WRITER_TESTS = (
        "test_main.TestMainHTTPHandleMethodsRouting."
        "test_handle_memory_store_creates_entry",
        "test_main_extended.TestHandleMemoryStoreExtended."
        "test_memory_store_with_tags",
        "test_main_extended.TestHandleMemoryStoreExtended."
        "test_memory_store_invalid_type_defaults_user",
        "test_main_fastapi.TestFastAPIEndpoints."
        "test_memory_store_returns_success",
        "test_main_fastapi.TestMainFastapiIntegration."
        "test_memory_store_returns_success",
        "test_main_fastapi.TestMainFastapiIntegration."
        "test_memory_probe_can_be_deleted_by_returned_id",
        "test_main_fastapi_extended.TestMemoryEndpoints."
        "test_memory_store_requires_content",
    )

    def test_memory_writer_tests_never_use_default_stores(self):
        modules = {
            name: importlib.import_module(name)
            for name in (
                "test_main",
                "test_main_extended",
                "test_main_fastapi",
                "test_main_fastapi_extended",
            )
        }
        main_fastapi = importlib.import_module("main_fastapi")
        default_stores = {
            id(store): store
            for store in (
                modules["test_main"]._main.state.memory_store,
                modules["test_main_extended"].state.memory_store,
                main_fastapi._default_state.memory_store,
            )
        }.values()

        def reject_default_store(*_args, **_kwargs):
            raise AssertionError("test wrote through a process-global memory store")

        suite = unittest.defaultTestLoader.loadTestsFromNames(self.WRITER_TESTS)
        result = unittest.TestResult()
        with ExitStack() as patches:
            for store in default_stores:
                patches.enter_context(
                    patch.object(store, "store", side_effect=reject_default_store)
                )
            suite.run(result)

        details = "\n".join(
            f"{case.id()}: {traceback}"
            for case, traceback in result.failures + result.errors
        )
        self.assertEqual(result.testsRun, len(self.WRITER_TESTS), details)
        self.assertTrue(result.wasSuccessful(), details)


class TestRunAllCoverage(unittest.TestCase):
    def test_legacy_app_state_tests_close_terminal_worker_directories(self):
        targets = (
            "tests.test_main_extended.TestAppStateExtended",
            "tests.test_main_fastapi_extended.TestAppState",
        )
        for target in targets:
            with self.subTest(target=target):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-W",
                        "always::ResourceWarning",
                        "-m",
                        "unittest",
                        target,
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr[-4000:])
                self.assertNotIn("jarvis-terminal-worker-", completed.stderr)
                self.assertNotIn("Implicitly cleaning up", completed.stderr)

    def test_store_performance_does_not_leave_repository_scratch(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory(prefix=".test-run-all-") as temporary:
            temporary_root = Path(temporary)
            try:
                os.chdir(temporary_root)
                result = unittest.TestResult()
                run_all.TestPerformance("test_store_speed").run(result)
            finally:
                os.chdir(original_cwd)

            self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
            self.assertFalse((temporary_root / ".test-perf").exists())

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
            aggregate_title = run_all.aggregate_suite_title()
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
        # Compared against the helper rather than a literal, because the
        # literal encoded the old bug: the runner printed the suite class
        # name instead of the suite it was actually given.
        self.assertEqual(payload["title"], aggregate_title)
        self.assertIn("aggregate", payload["title"])
        self.assertIn("2 classes, 2 tests", payload["title"])

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
        self.assertEqual(payload["title"], run_all.smoke_suite_title())
        self.assertIn(f"{smoke_count} tests", payload["title"])
        self.assertEqual(payload["timeout_seconds"], timeout)

        report.unlink()

    def test_aggregate_runner_includes_documentation_and_config_guards(self):
        case_names = {case.__name__ for case in run_all.AGGREGATE_TEST_CASES}

        self.assertIn("TestReadme", case_names)
        self.assertIn("TestSetupDocs", case_names)
        self.assertIn("TestPythonDependencies", case_names)
        self.assertIn("TestPythonDependencyLock", case_names)
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

        self.assertIn(
            ("test_plugin_worker_protocol", "TestPluginWorkerProtocol"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_windows_isolation_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_worker_windows_isolation", "TestWindowsIsolationContract"),
            case_ids,
        )
        self.assertIn(
            ("test_worker_windows_isolation", "TestWindowsIsolationRealEnforcement"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_linux_enforcement_guard_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_linux_worker_isolation_enforcement",
                "TestLinuxWorkerIsolationEnforcement",
            ),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_linux_plugin_runtime_enforcement_guard_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_linux_plugin_runtime_enforcement",
                "TestLinuxPluginRuntimeEnforcement",
            ),
            case_ids,
        )
        self.assertIn(
            (
                "test_linux_plugin_runtime_enforcement",
                "TestLinuxPluginRuntimeProbeHarness",
            ),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_linux_terminal_worker_enforcement_guard_once(
        self,
    ):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_linux_terminal_worker_enforcement",
                "TestLinuxTerminalWorkerEnforcement",
            ),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_orchestrator_timeout_quarantine_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_orchestrator_extended_v2",
                "TestOrchestratorTimeoutQuarantine",
            ),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_declared_orchestrator_worker_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_orchestrator_extended_v2",
                "TestOrchestratorDeclaredWorker",
            ),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_importable_orchestrator_worker_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_orchestrator_extended_v2",
                "TestOrchestratorImportableWorker",
            ),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_orchestrator_history_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_orchestrator_extended_v2",
                "TestOrchestratorHistoryOwnership",
            ),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_token_usage_state_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_ollama_manager", "TestTokenUsage"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_llm_compression_history_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_context_compressor_llm", "TestLLMCompressorHistory"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_event_bus_state_guards_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_event_bus_extended", "TestEventBusStateBoundaries"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_plugin_broker_guard_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_plugin_broker", "TestPluginBroker"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_plugin_sdk_worker_guard_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_plugin_sdk", "TestPluginWorkerCoordinator"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_plugin_api_audit_guard_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_plugin_sdk", "TestXiaoYiPluginAPI"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_python_dependency_lock_guard_once(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            ("test_python_dependency_lock", "TestPythonDependencyLock"),
            case_ids,
        )
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_terminal_policy_parameter_guards(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]
        expected = {
            (
                "test_terminal_executor_extended_v2",
                "TestTerminalExecutorExecuteShell",
            ),
            (
                "test_terminal_executor_extended_v2",
                "TestTerminalExecutorDeniedCommands",
            ),
            (
                "test_terminal_executor_extended_v2",
                "TestTerminalExecutorLifecycle",
            ),
        }

        self.assertLessEqual(expected, set(case_ids))
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_aggregate_runner_includes_terminal_audit_guards(self):
        case_ids = [
            (case.__module__, case.__name__)
            for case in run_all.AGGREGATE_TEST_CASES
        ]

        self.assertIn(
            (
                "test_terminal_executor_extended_v2",
                "TestTerminalExecutorAuditLog",
            ),
            case_ids,
        )
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
            ("test_role_tool_catalog", "TestRoleToolCatalog"),
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

        self.assertIn("aggregate", title)
        self.assertIn(f"{len(run_all.AGGREGATE_TEST_CASES)} classes", title)
        self.assertIn(f"{run_all.canonical_test_count()} tests", title)
        self.assertNotIn("Iteration 141", title)

    def test_smoke_suite_title_is_distinct_from_the_aggregate_title(self):
        smoke = run_all.smoke_suite_title()

        self.assertIn("smoke", smoke)
        self.assertIn(f"{len(run_all.SMOKE_TEST_CASES)} classes", smoke)
        self.assertIn(
            f"{run_all.build_smoke_suite().countTestCases()} tests", smoke
        )
        self.assertNotEqual(smoke, run_all.aggregate_suite_title())

    def test_cli_parses_smoke_timeout_and_report_options(self):
        parser = run_all.build_argument_parser()

        defaults = parser.parse_args([])
        self.assertFalse(defaults.smoke)
        self.assertEqual(defaults.timeout, 0)
        self.assertEqual(defaults.json_report, "")

        parsed = parser.parse_args(
            ["--smoke", "--timeout", "30", "--json-report", "out.json"]
        )
        self.assertTrue(parsed.smoke)
        self.assertEqual(parsed.timeout, 30)
        self.assertEqual(parsed.json_report, "out.json")

    def test_cli_rejects_invalid_timeout_values(self):
        parser = run_all.build_argument_parser()
        for invalid in ("-1", "abc", "1.5"):
            with self.subTest(value=invalid):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["--timeout", invalid])

    def test_cli_smoke_flag_selects_only_the_smoke_subset(self):
        report = run_all.ROOT / ".test-run-all-cli-smoke.json"
        if report.exists():
            report.unlink()

        # The exit code is deliberately not asserted. The smoke subset
        # contains TestIterationLedger, so it fails whenever the ledger
        # numbers are stale. This test only proves the flag selects the
        # subset, which the report proves on its own.
        run_all.main(["--smoke", "--json-report", str(report)])

        payload = __import__("json").loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["title"], run_all.smoke_suite_title())
        self.assertEqual(
            payload["tests"], run_all.build_smoke_suite().countTestCases()
        )
        self.assertLess(payload["tests"], run_all.canonical_test_count())

        report.unlink()

    def test_module_entrypoint_dispatches_through_the_cli(self):
        # main() is exercised directly elsewhere. This runs the file the way
        # CI and the docs run it, so a __main__ block wired straight to
        # run_all_tests() (ignoring every flag) is caught.
        runner = run_all.ROOT / "tests" / "run_all.py"
        report = run_all.ROOT / ".test-run-all-entrypoint.json"
        if report.exists():
            report.unlink()
        try:
            usage = subprocess.run(
                [sys.executable, str(runner), "--help"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(usage.returncode, 0, usage.stderr[-2000:])
            for flag in ("--smoke", "--timeout", "--json-report"):
                self.assertIn(flag, usage.stdout)

            completed = subprocess.run(
                [sys.executable, str(runner), "--smoke", "--json-report", str(report)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            self.assertIn(run_all.smoke_suite_title(), completed.stdout)
            payload = __import__("json").loads(report.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["tests"], run_all.build_smoke_suite().countTestCases()
            )
        finally:
            if report.exists():
                report.unlink()

    def test_timeout_worker_is_a_daemon_thread(self):
        import ast
        import inspect

        source = inspect.getsource(run_all._run_suite)
        call = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Thread"
        )
        daemon = {
            keyword.arg: keyword.value for keyword in call.keywords
        }.get("daemon")

        self.assertIsNotNone(daemon, "timeout worker must declare daemon")
        self.assertTrue(ast.literal_eval(daemon))

    def test_cli_timeout_exits_without_waiting_for_a_hung_test(self):
        report = run_all.ROOT / ".test-run-all-cli-timeout.json"
        driver = run_all.ROOT / ".test-run-all-cli-timeout-driver.py"
        for path in (report, driver):
            if path.exists():
                path.unlink()

        tests_dir = run_all.ROOT / "tests"
        driver.write_text(
            "import sys, time, unittest\n"
            f"sys.path.insert(0, r'{tests_dir}')\n"
            "import run_all\n"
            "Hang = type('Hang', (unittest.TestCase,), "
            "{'test_hangs': lambda self: time.sleep(120)})\n"
            "run_all.AGGREGATE_TEST_CASES[:] = [Hang]\n"
            "sys.exit(run_all.main("
            f"['--timeout', '2', '--json-report', r'{report}']))\n",
            encoding="utf-8",
        )
        try:
            started = time.monotonic()
            completed = subprocess.run(
                [sys.executable, str(driver)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            elapsed = time.monotonic() - started

            self.assertEqual(completed.returncode, 1, completed.stderr[-2000:])
            self.assertLess(elapsed, 30, "hung test must not delay the exit")
            payload = __import__("json").loads(
                report.read_text(encoding="utf-8")
            )
            self.assertTrue(payload["timeout_expired"])
            self.assertFalse(payload["success"])
            self.assertEqual(payload["timeout_seconds"], 2)
        finally:
            for path in (report, driver):
                if path.exists():
                    path.unlink()


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestRunAllCoverage)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
