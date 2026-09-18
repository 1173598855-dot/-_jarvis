"""
J.A.R.V.I.S. test suite - Iteration 141
Run: python tests/run_all.py
"""

# Aggregate-runner path bootstrap must precede project and test imports.
# ruff: noqa: E402

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from test_agent_factory import TestOllamaRoleExecution
from test_api_contract import TestSharedApiContract
from test_bounded_cli_inputs import TestBoundedJsonReader, TestCliJsonLimits
from test_capability_registry import TestCapabilityRecord, TestCapabilityRegistry
from test_capability_resolver import (
    TestCapabilityQuery,
    TestCapabilityResolver,
    TestCompatibilityEvaluation,
)
from test_ci_integration_bounds import (
    TestHealthWaitFailsFast,
    TestOverallDeadlineAccounting,
    TestParserBounds,
    TestProfileRunsUnderItsBudget,
    TestRunIntegrationBoundsTheWholeRun,
    TestServiceLogTails,
    TestTreeReclamation,
)
from test_ci_integration_output_encoding import (
    TestChildEnvironmentForcesUtf8,
    TestFailureTailSurfacesRealErrors,
    TestServiceOutputDecoding,
)
from test_ci_integration_resource_ownership import (
    TestLogDirectoryCleanupNeverMasksTheResult,
    TestPortReservationHoldsThePort,
    TestReservedPortsAreDistinct,
    TestRunnerReleasesBeforeEachChild,
)
from test_context_budget import TestContextBudgetMonitor
from test_context_compressor import TestMemoryStore as TestContextMemoryStore
from test_context_compressor import (
    TestMemoryStoreConsolidateRemoval,
    TestMemoryStoreJournal,
    TestMemoryStoreLosslessMerge,
    TestSemanticCompressorBoundedTransforms,
)
from test_context_compressor_llm import TestLLMCompressorHistory
from test_discover_tests_runner import (
    TestDiscoveryCommand,
    TestDiscoveryProgress,
    TestDiscoveryRunnerEndToEnd,
    TestRunDiscoveryInProcess,
    TestTerminateProcessTree,
)
from test_docs_setup import TestSetupDocs
from test_durable_directory import TestFsyncDirectory, TestSupportsDirectoryFsync
from test_event_bus_extended import TestEventBusStateBoundaries
from test_file_capability_store import (
    TestCapabilityPackageLimits,
    TestCapabilityPackageRejection,
    TestFileCapabilityStore,
)
from test_file_run_state_repository import TestFileRunStateRepository
from test_iteration_ledger import TestIterationLedger
from test_linux_plugin_runtime_enforcement import (
    TestLinuxPluginRuntimeEnforcement,
    TestLinuxPluginRuntimeProbeHarness,
)
from test_linux_terminal_worker_enforcement import TestLinuxTerminalWorkerEnforcement
from test_linux_worker_isolation_enforcement import TestLinuxWorkerIsolationEnforcement
from test_local_integration_profile import TestLocalIntegrationProfile
from test_local_integration_runner import TestLocalIntegrationRunner
from test_main import (
    TestMainHTTPEdgeCases,
    TestMainHTTPGETRouting,
    TestMainHTTPHandleMethodsRouting,
    TestMainHTTPHelpers,
    TestMainHTTPPOSTRouting,
    TestMainHTTPRoleDispatchWorkerAdapter,
    TestMainHTTPStateLifecycle,
)
from test_main_fastapi import (
    TestMainFastapiIntegration,
    TestRequestBodyLimitMiddleware,
    TestRoleDispatchEndpoints,
    TestRoleTaskLifecycleEndpoints,
    TestRunRecoveryLifespan,
)
from test_ollama_manager import TestBoundedOllamaResponses, TestTokenUsage
from test_ollama_manager import TestChat as TestOllamaChat
from test_ollama_manager_extended import TestOllamaManagerChat
from test_orchestrator_extended_v2 import (
    TestOrchestratorDeclaredWorker,
    TestOrchestratorHistoryOwnership,
    TestOrchestratorImportableWorker,
    TestOrchestratorTimeoutQuarantine,
)
from test_phase_a_recovery import TestPhaseARecoveryGate
from test_plugin_broker import (
    TestPluginBroker,
    TestPluginBrokerFileList,
    TestPluginBrokerNetworkGet,
)
from test_plugin_installation import TestPluginInstallation
from test_plugin_sdk import (
    TestPluginManagerBrokerRegistration,
    TestPluginWorkerCoordinator,
    TestXiaoYiPluginAPI,
)
from test_plugin_worker_entrypoint import TestPluginWorkerEntrypoint
from test_plugin_worker_protocol import TestPluginWorkerProtocol
from test_process_containment import TestProcessTreeContainment
from test_project_config import TestPythonDependencies
from test_python_dependency_lock import TestPythonDependencyLock
from test_read_only_role_tools import TestReadOnlyRoleTools
from test_readme import TestReadme
from test_resume_document import TestResumeDocument
from test_role_dispatch_service import (
    TestRoleDispatchServiceBatch,
    TestRoleDispatchServiceLeases,
    TestRoleDispatchServiceLockOrder,
    TestRoleDispatchServiceSelectionAndMapping,
)
from test_role_registry_extended_v2 import (
    TestRoleRegistryCLI,
    TestRoleRegistryDeepInheritance,
    TestRoleRegistryInheritanceCycles,
    TestRoleRegistrySnapshotOwnership,
)
from test_role_tool_catalog import TestRoleToolCatalog
from test_role_tool_loop import TestRoleToolLoop
from test_role_tool_protocol import TestRoleToolProtocol
from test_role_tools import TestRoleToolBroker
from test_role_worker import TestRoleWorkerSupervisor
from test_ruff_check import TestRuffCheckOutputLimits
from test_run_lifecycle import TestGitWorkspaceInspector, TestRunLifecycleCoordinator
from test_run_state import TestRunState
from test_secret_redaction import TestSecretRedaction
from test_terminal_executor_extended_v2 import (
    TestTerminalExecutorAuditLog,
    TestTerminalExecutorDeniedCommands,
    TestTerminalExecutorExecuteShell,
    TestTerminalExecutorLifecycle,
    TestTerminalExecutorProcessOutput,
)
from test_terminal_worker import TestTerminalWorker
from test_worker_filesystem_isolation import TestWorkerFilesystemIsolation
from test_worker_macos_sandbox import TestMacOSSandboxContract
from test_worker_network_isolation import TestWorkerNetworkIsolation
from test_worker_protocol import TestWorkerProtocol
from test_worker_resource_limits import TestWorkerResourceLimits
from test_worker_windows_container import TestWindowsContainerContract
from test_worker_windows_isolation import (
    TestWindowsIsolationContract,
    TestWindowsIsolationRealEnforcement,
)

from core.brain.context_compressor import ContextCompressor, MemoryEntry, MemoryStore, MemoryType
from core.brain.role_registry import AgentProfile, RoleRegistry, create_default_registry
from core.kernel.ollama_manager import OllamaModel
from core.kernel.terminal_executor import CommandRisk, TerminalCommand, TerminalExecutor


class TestContextCompressor(unittest.TestCase):
    def setUp(self):
        self.compressor = ContextCompressor(max_tokens=4000)

    def test_compress_short(self):
        conv = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        r = self.compressor.compress(conv)
        self.assertIn("hi", r)
        self.assertNotIn("[摘要]", r)

    def test_compress_long(self):
        conv = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        r = self.compressor.compress(conv)
        self.assertIn("[摘要]", r)

    def test_summarize_decisions(self):
        msgs = [{"role": "user", "content": "决定使用 TS"}]
        s = self.compressor._summarize(msgs)
        self.assertIn("决定", s)


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        import uuid
        self.td = Path(f".test-mem-{uuid.uuid4().hex[:8]}")
        self.td.mkdir(exist_ok=True)
        self.store = MemoryStore(memory_dir=str(self.td))

    def tearDown(self):
        import os
        if self.td.exists():
            for root, dirs, files in os.walk(self.td, topdown=False):
                for f in files:
                    try:
                        Path(root, f).unlink()
                    except PermissionError:
                        pass
            try:
                self.td.rmdir()
            except PermissionError:
                pass

    def test_store_load(self):
        store = MemoryStore(memory_dir=str(self.td))
        e = MemoryEntry.create(MemoryType.USER, "t1", "c1", tags=["t"])
        p = store.store(e)
        self.assertTrue(Path(p).exists())
        entries = store.load()
        self.assertEqual(len(entries), 1)

    def test_index(self):
        store = MemoryStore(memory_dir=str(self.td))
        e = MemoryEntry.create(MemoryType.PROJECT, "idx", "content")
        store.store(e)
        self.assertIn("idx", store.index_file.read_text())

    def test_consolidate(self):
        store = MemoryStore(memory_dir=str(self.td))
        e1 = MemoryEntry.create(MemoryType.USER, "same", "a")
        e2 = MemoryEntry.create(MemoryType.USER, "same", "b")
        store.store(e1)
        store.store(e2)
        stats = store.consolidate()
        self.assertGreaterEqual(stats["merged"], 0)


class TestOllamaManager(unittest.TestCase):
    def test_model(self):
        m = OllamaModel(name="llama3", size="4000000000", digest="abc", modified_at="2026-07-08")
        self.assertEqual(m.name, "llama3")


class TestAgentProfile(unittest.TestCase):
    def test_resolve_prompt(self):
        p = AgentProfile(name="e", display_name="Engineer", description="Coding",
                         prompt_template="Role: {name}. Task: {task}")
        r = p.resolve_prompt("fix bug")
        self.assertIn("Engineer", r)
        self.assertIn("fix bug", r)

    def test_to_from_dict(self):
        p = AgentProfile(name="pm", display_name="PM", description="Product", capabilities=["req"], priority=8)
        p2 = AgentProfile.from_dict(p.to_dict())
        self.assertEqual(p.name, p2.name)
        self.assertEqual(p.capabilities, p2.capabilities)


class TestRoleRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = RoleRegistry()

    def test_register_get(self):
        p = AgentProfile(name="t1", display_name="T1", description="d")
        self.reg.register(p)
        self.assertIsNotNone(self.reg.get("t1"))

    def test_default_registry_roles(self):
        reg = create_default_registry()
        expected_default_names = [
            "architect",
            "engineer",
            "reviewer",
            "tester",
            "product_manager",
        ]
        for name in expected_default_names:
            self.assertIsNotNone(reg.get(name), msg=name)
        self.assertEqual(len(expected_default_names), 5)


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.td = Path(".test-int")
        self.td.mkdir(exist_ok=True)

    def tearDown(self):
        import os
        if self.td.exists():
            for root, dirs, files in os.walk(self.td, topdown=False):
                for f in files:
                    try:
                        Path(root, f).unlink()
                    except PermissionError:
                        pass
            try:
                self.td.rmdir()
            except PermissionError:
                pass

    def test_pipeline(self):
        c = ContextCompressor()
        conv = [{"role": "user", "content": f"m{i}"} for i in range(10)]
        compressed = c.compress(conv)
        store = MemoryStore(memory_dir=str(self.td))
        e = MemoryEntry.create(MemoryType.PROJECT, "summary", compressed, tags=["auto"])
        store.store(e)
        entries = store.load(MemoryType.PROJECT)
        self.assertEqual(len(entries), 1)
        self.assertIn("[摘要]", entries[0].content)


class TestPerformance(unittest.TestCase):
    def test_compression_speed(self):
        c = ContextCompressor()
        conv = [{"role": "user", "content": f"msg {i}" * 10} for i in range(100)]
        t0 = time.time()
        c.compress(conv)
        ms = (time.time() - t0) * 1000
        self.assertLess(ms, 100, f"压缩 {ms:.1f}ms > 100ms")
        print(f"compress: {ms:.1f}ms")

    def test_store_speed(self):
        with tempfile.TemporaryDirectory(prefix=".test-perf-") as memory_dir:
            s = MemoryStore(memory_dir=memory_dir)
            t0 = time.time()
            for i in range(10):
                s.store(MemoryEntry.create(MemoryType.USER, f"t{i}", f"c{i}"))
            ms = (time.time() - t0) * 1000
            self.assertLess(ms, 500)
            print(f"store: {ms:.1f}ms")


class TestTerminalExecutor(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        self.Ex = TerminalExecutor
        self.Cmd = TerminalCommand
        self.Risk = CommandRisk

    def test_safe_cmd(self):
        ex = self.Ex()
        cmd = self.Cmd(id="t1", command="echo", args=["hello"], risk_level=self.Risk.SAFE)
        r = ex.execute(cmd)
        self.assertTrue(r.success)
        self.assertIn("hello", r.stdout)

    def test_danger_blocked(self):
        ex = self.Ex()
        cmd = self.Cmd(id="t2", command="rm", args=["-rf", "/"], risk_level=self.Risk.DANGEROUS)
        r = ex.execute(cmd)
        self.assertFalse(r.success)
        self.assertIn("Security block", r.stderr)

    def test_unknown_blocked(self):
        ex = self.Ex()
        cmd = self.Cmd(id="t3", command="badcmd", args=[], risk_level=self.Risk.DANGEROUS)
        r = ex.execute(cmd)
        self.assertFalse(r.success)

    def test_risk(self):
        ex = self.Ex()
        self.assertEqual(ex._assess_risk("ls"), self.Risk.SAFE)
        self.assertEqual(ex._assess_risk("rm"), self.Risk.DANGEROUS)
        self.assertEqual(ex._assess_risk("mv"), self.Risk.MODERATE)


AGGREGATE_TEST_CASES = [
    TestContextCompressor,
    TestLLMCompressorHistory,
    TestMemoryStore,
    TestEventBusStateBoundaries,
    TestOllamaManager,
    TestAgentProfile,
    TestRoleRegistry,
    TestRoleRegistryCLI,
    TestRoleRegistryDeepInheritance,
    TestRoleRegistryInheritanceCycles,
    TestRoleRegistrySnapshotOwnership,
    TestIntegration,
    TestPerformance,
    TestTerminalExecutor,
    TestTerminalExecutorExecuteShell,
    TestTerminalExecutorDeniedCommands,
    TestTerminalExecutorLifecycle,
    TestTerminalExecutorProcessOutput,
    TestTerminalExecutorAuditLog,
    TestTerminalWorker,
    TestSharedApiContract,
    TestReadme,
    TestSetupDocs,
    TestPythonDependencies,
    TestPythonDependencyLock,
    TestIterationLedger,
    TestMainHTTPHelpers,
    TestMainHTTPGETRouting,
    TestMainHTTPPOSTRouting,
    TestMainHTTPHandleMethodsRouting,
    TestMainHTTPRoleDispatchWorkerAdapter,
    TestMainHTTPStateLifecycle,
    TestMainHTTPEdgeCases,
    TestOrchestratorTimeoutQuarantine,
    TestOrchestratorDeclaredWorker,
    TestOrchestratorImportableWorker,
    TestOrchestratorHistoryOwnership,
    TestMainFastapiIntegration,
    TestRequestBodyLimitMiddleware,
    TestRoleTaskLifecycleEndpoints,
    TestRoleDispatchEndpoints,
    TestRunRecoveryLifespan,
    TestLocalIntegrationProfile,
    TestLocalIntegrationRunner,
    TestOverallDeadlineAccounting,
    TestHealthWaitFailsFast,
    TestProfileRunsUnderItsBudget,
    TestRunIntegrationBoundsTheWholeRun,
    TestParserBounds,
    TestTreeReclamation,
    TestServiceOutputDecoding,
    TestFailureTailSurfacesRealErrors,
    TestChildEnvironmentForcesUtf8,
    TestLogDirectoryCleanupNeverMasksTheResult,
    TestPortReservationHoldsThePort,
    TestReservedPortsAreDistinct,
    TestRunnerReleasesBeforeEachChild,
    TestServiceLogTails,
    TestOllamaChat,
    TestBoundedOllamaResponses,
    TestTokenUsage,
    TestOllamaManagerChat,
    TestPluginInstallation,
    TestPluginBroker,
    TestPluginBrokerFileList,
    TestPluginBrokerNetworkGet,
    TestPluginManagerBrokerRegistration,
    TestXiaoYiPluginAPI,
    TestPluginWorkerCoordinator,
    TestPluginWorkerEntrypoint,
    TestPluginWorkerProtocol,
    TestProcessTreeContainment,
    TestRunState,
    TestRuffCheckOutputLimits,
    TestDiscoveryProgress,
    TestDiscoveryCommand,
    TestTerminateProcessTree,
    TestRunDiscoveryInProcess,
    TestDiscoveryRunnerEndToEnd,
    TestContextBudgetMonitor,
    TestResumeDocument,
    TestFileRunStateRepository,
    TestRunLifecycleCoordinator,
    TestGitWorkspaceInspector,
    TestPhaseARecoveryGate,
    TestWorkerProtocol,
    TestWorkerResourceLimits,
    TestWorkerNetworkIsolation,
    TestWorkerFilesystemIsolation,
    TestLinuxPluginRuntimeProbeHarness,
    TestLinuxPluginRuntimeEnforcement,
    TestLinuxTerminalWorkerEnforcement,
    TestLinuxWorkerIsolationEnforcement,
    TestMacOSSandboxContract,
    TestWindowsIsolationContract,
    TestWindowsIsolationRealEnforcement,
    TestWindowsContainerContract,
    TestRoleWorkerSupervisor,
    TestBoundedJsonReader,
    TestCliJsonLimits,
    TestRoleDispatchServiceSelectionAndMapping,
    TestRoleDispatchServiceLeases,
    TestRoleDispatchServiceLockOrder,
    TestRoleDispatchServiceBatch,
    TestOllamaRoleExecution,
    TestContextMemoryStore,
    TestMemoryStoreJournal,
    TestMemoryStoreConsolidateRemoval,
    TestMemoryStoreLosslessMerge,
    TestSemanticCompressorBoundedTransforms,
    TestSupportsDirectoryFsync,
    TestFsyncDirectory,
    TestRoleToolCatalog,
    TestRoleToolProtocol,
    TestRoleToolBroker,
    TestRoleToolLoop,
    TestReadOnlyRoleTools,
    TestSecretRedaction,
    TestCapabilityRecord,
    TestCapabilityRegistry,
    TestCompatibilityEvaluation,
    TestCapabilityQuery,
    TestCapabilityResolver,
    TestCapabilityPackageLimits,
    TestCapabilityPackageRejection,
    TestFileCapabilityStore,
]


def canonical_test_count():
    loader = unittest.TestLoader()
    return sum(
        loader.loadTestsFromTestCase(tc).countTestCases()
        for tc in AGGREGATE_TEST_CASES
    )


def _suite_title(label: str, cases: list) -> str:
    loader = unittest.TestLoader()
    tests = sum(loader.loadTestsFromTestCase(tc).countTestCases() for tc in cases)
    return (
        f"J.A.R.V.I.S. test suite - {label} "
        f"({len(cases)} classes, {tests} tests)"
    )


def aggregate_suite_title():
    return _suite_title("aggregate", AGGREGATE_TEST_CASES)


def smoke_suite_title():
    return _suite_title("smoke", SMOKE_TEST_CASES)


SMOKE_TEST_CASES = [
    TestReadme,
    TestSetupDocs,
    TestPythonDependencies,
    TestIterationLedger,
    TestPluginInstallation,
]


def build_aggregate_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for tc in AGGREGATE_TEST_CASES:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    return suite


def build_smoke_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for tc in SMOKE_TEST_CASES:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    return suite


def run_all_tests(timeout: int = 0, json_report: str = ""):
    return _run_suite(
        build_aggregate_suite(),
        timeout=timeout,
        json_report=json_report,
        title=aggregate_suite_title(),
    )


def run_smoke_tests(timeout: int = 0, json_report: str = ""):
    return _run_suite(
        build_smoke_suite(),
        timeout=timeout,
        json_report=json_report,
        title=smoke_suite_title(),
    )


def _write_report(json_report: str, payload: dict) -> None:
    if not json_report:
        return
    Path(json_report).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_suite(
    suite,
    timeout: int = 0,
    json_report: str = "",
    title: str = "",
    abandon_on_timeout: bool = False,
):
    timeout_expired = threading.Event()
    result_holder = {}
    print("=" * 60)
    if not title:
        title = f"J.A.R.V.I.S. test suite - {suite.countTestCases()} tests"
    print(title)
    print("=" * 60)

    def run_suite():
        result_holder["result"] = unittest.TextTestRunner(verbosity=2).run(suite)

    # The worker is a daemon so a wedged test cannot keep the interpreter alive
    # after the deadline. Without this, a timeout returned an exit code the
    # process could not act on until the hung test finally finished.
    thread = threading.Thread(target=run_suite, daemon=True)
    thread.start()
    thread.join(timeout=timeout if timeout > 0 else None)

    if thread.is_alive():
        timeout_expired.set()
        print(f"\nTimeout: {timeout}s exceeded")
        _write_report(json_report, {
            "title": title,
            "tests": 0,
            "passed": 0,
            "skipped": 0,
            "failures": 0,
            "errors": 0,
            "success": False,
            "timeout_seconds": timeout,
            "timeout_expired": True,
        })
        if abandon_on_timeout:
            # A daemon thread stuck in a C call or holding a lock can still
            # block interpreter shutdown, so the CLI leaves immediately with
            # the report already flushed.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
        return 1

    result = result_holder.get("result", unittest.TestResult())
    print()
    print("=" * 60)
    total = result.testsRun
    skipped = len(result.skipped)
    passed = total - len(result.failures) - len(result.errors) - skipped
    print(
        f"Results: {total} tests, {passed} passed, {skipped} skipped, "
        f"{len(result.failures)} failed, {len(result.errors)} errors"
    )
    print("=" * 60)
    _write_report(json_report, {
        "title": title,
        "tests": total,
        "passed": passed,
        "skipped": skipped,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "success": result.wasSuccessful(),
        "timeout_seconds": timeout,
        "timeout_expired": timeout_expired.is_set(),
    })
    return 0 if result.wasSuccessful() else 1


def _non_negative_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be an integer") from None
    if seconds < 0:
        raise argparse.ArgumentTypeError("timeout must not be negative")
    return seconds


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_all.py",
        description="Run the canonical aggregate suite or the smoke subset.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run the documentation and ledger smoke subset instead of the aggregate suite",
    )
    parser.add_argument(
        "--timeout",
        type=_non_negative_seconds,
        default=0,
        metavar="SECONDS",
        help="fail the run after SECONDS instead of waiting forever (0 disables)",
    )
    parser.add_argument(
        "--json-report",
        default="",
        metavar="PATH",
        help="write the run summary to PATH as JSON",
    )
    return parser


def main(argv=None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    suite = build_smoke_suite() if arguments.smoke else build_aggregate_suite()
    title = smoke_suite_title() if arguments.smoke else aggregate_suite_title()
    return _run_suite(
        suite,
        timeout=arguments.timeout,
        json_report=arguments.json_report,
        title=title,
        abandon_on_timeout=True,
    )


if __name__ == "__main__":
    sys.exit(main())
