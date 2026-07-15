"""Regression tests for the process-isolated terminal worker."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.kernel.terminal_executor import CommandRisk, TerminalCommand, TerminalExecutor
from core.kernel.terminal_worker import TerminalWorker


def _load_http_main():
    import importlib.util

    path = Path(__file__).parent.parent / "src" / "main.py"
    spec = importlib.util.spec_from_file_location("terminal_worker_http_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTerminalWorker(unittest.TestCase):
    def test_default_worker_executes_fixed_read_only_operation(self):
        worker = TerminalWorker()
        try:
            result = worker.execute(
                TerminalCommand(
                    id="worker-echo",
                    command="echo",
                    args=["hello"],
                    timeout=5,
                    risk_level=CommandRisk.SAFE,
                )
            )
            self.assertTrue(result.success)
            self.assertIn("hello", result.stdout)
        finally:
            worker.close()

    def test_worker_diagnostics_are_platform_independent(self):
        worker = TerminalWorker()
        try:
            result = worker.execute(
                TerminalCommand(id="worker-pwd", command="pwd", timeout=5)
            )
            self.assertTrue(result.success)
            self.assertIn("jarvis-terminal", result.stdout)
            self.assertEqual(result.exit_code, 0)
        finally:
            worker.close()

    def test_worker_rejects_interpreter_and_environment_overrides(self):
        worker = TerminalWorker()
        try:
            result = worker.execute(
                TerminalCommand(
                    id="worker-python",
                    command="python",
                    args=["-c", "print(1)"],
                    timeout=5,
                    risk_level=CommandRisk.DANGEROUS,
                )
            )
            self.assertFalse(result.success)
            self.assertIn("not available", result.stderr.lower())

            result = worker.execute(
                TerminalCommand(
                    id="worker-env",
                    command="echo",
                    args=["blocked"],
                    env={"SECRET": "value"},
                    timeout=5,
                    risk_level=CommandRisk.SAFE,
                )
            )
            self.assertFalse(result.success)
            self.assertIn("environment overrides", result.stderr)
        finally:
            worker.close()

    def test_worker_has_owned_sandbox_and_close_is_explicit(self):
        worker = TerminalWorker()
        sandbox_dir = worker.sandbox_dir
        self.assertTrue(sandbox_dir.is_dir())
        worker.close()
        self.assertFalse(os.path.exists(sandbox_dir))
        result = worker.execute(
            TerminalCommand(id="closed", command="pwd", timeout=5)
        )
        self.assertFalse(result.success)
        self.assertIn("closed", result.stderr.lower())

    def test_services_can_inject_an_explicit_executor(self):
        import main_fastapi
        main = _load_http_main()

        explicit = TerminalExecutor(sandbox=False)
        state = main.AppState(terminal=explicit)
        self.assertIs(state.terminal, explicit)

        explicit_fastapi = TerminalExecutor(sandbox=False)
        fastapi_state = main_fastapi.AppState(terminal=explicit_fastapi)
        self.assertIs(fastapi_state.terminal, explicit_fastapi)

    def test_services_default_to_the_process_worker(self):
        import main_fastapi
        main = _load_http_main()

        http_state = main.AppState()
        fastapi_state = main_fastapi.AppState()
        try:
            self.assertIsInstance(http_state.terminal, TerminalWorker)
            self.assertIsInstance(fastapi_state.terminal, TerminalWorker)
        finally:
            http_state.terminal.close()
            fastapi_state.terminal.close()

    def test_worker_launch_environment_does_not_include_service_token(self):
        worker = TerminalWorker()
        try:
            with patch.dict(
                os.environ,
                {
                    "JARVIS_TERMINAL_TOKEN": "secret",
                    "JARVIS_TEST_SECRET": "secret-2",
                },
            ), patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
                popen.return_value.communicate.return_value = (
                    '{"command_id":"x","exit_code":0,"stdout":"ok",'
                    '"stderr":"","duration":0.1,"success":true,"risk_level":"safe",'
                    '"timestamp":"now"}',
                )
                popen.return_value.returncode = 0
                worker.execute(TerminalCommand(id="x", command="echo", args=["ok"], timeout=5))
                environment = popen.call_args.kwargs["env"]
                self.assertNotIn("JARVIS_TERMINAL_TOKEN", environment)
                self.assertNotIn("JARVIS_TEST_SECRET", environment)
                self.assertEqual(environment["PYTHONPATH"], str(Path(__file__).parent.parent / "src"))
        finally:
            worker.close()

    def test_worker_keeps_a_bounded_audit_log(self):
        worker = TerminalWorker()
        try:
            worker.execute(TerminalCommand(id="audit", command="pwd", timeout=5))
            self.assertEqual(worker.get_audit_log(limit=1)[0]["command_id"], "audit")
            worker.clear_audit_log()
            self.assertEqual(worker.get_audit_log(), [])
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
