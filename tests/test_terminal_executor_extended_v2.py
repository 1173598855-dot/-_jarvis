"""Extended tests v2 for terminal_executor.py - Iteration 55"""
import io
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.terminal_executor import (
    CommandRisk,
    TerminalCommand,
    TerminalExecutor,
    TerminalResult,
)


class _PendingBoundedProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"") -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = 0
        self.kill_calls = 0
        self._killed = False

    def poll(self):
        return self.returncode if self._killed else None

    def wait(self, timeout=None):
        if not self._killed:
            raise subprocess.TimeoutExpired("fixture", timeout)
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self._killed = True

    def communicate(self, *_args, **_kwargs):
        return (
            self.stdout.getvalue().decode("utf-8"),
            self.stderr.getvalue().decode("utf-8"),
        )


class TestTerminalExecutorExecuteShell(unittest.TestCase):
    def test_empty_shell_returns_error(self):
        ex = TerminalExecutor()
        result = ex.execute_shell("")
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, -1)

    def test_malformed_shell_syntax_returns_error(self):
        ex = TerminalExecutor()

        result = ex.execute_shell("echo 'unterminated")

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, -1)
        self.assertIn("No closing quotation", result.stderr)

    def test_shell_echo_succeeds(self):
        ex = TerminalExecutor()
        result = ex.execute_shell("echo hello")
        self.assertTrue(result.success)
        self.assertIn("hello", result.stdout)

    def test_shell_with_custom_timeout(self):
        ex = TerminalExecutor(default_timeout=7, sandbox=False, allow_caller_context=True)
        with patch("core.kernel.terminal_executor.subprocess.Popen") as process:
            process.return_value.communicate.return_value = ("out", "")
            process.return_value.returncode = 0

            result = ex.execute_shell("python --version", timeout=3)

        self.assertTrue(result.success)
        process.return_value.communicate.assert_called_once_with(timeout=3)

    def test_shell_uses_executor_default_timeout_when_omitted(self):
        ex = TerminalExecutor(default_timeout=7, sandbox=False, allow_caller_context=True)
        with patch("core.kernel.terminal_executor.subprocess.Popen") as process:
            process.return_value.communicate.return_value = ("out", "")
            process.return_value.returncode = 0

            result = ex.execute_shell("python --version")

        self.assertTrue(result.success)
        process.return_value.communicate.assert_called_once_with(timeout=7)


class TestTerminalExecutorProcessOutput(unittest.TestCase):
    def test_stdout_overflow_kills_child_before_result(self):
        executor = TerminalExecutor(
            allowed_commands=["python"],
            sandbox=False,
            allow_caller_context=True,
        )
        process = _PendingBoundedProcess(b"x" * (8 * 1024 * 1024 + 1))
        with patch(
            "core.kernel.terminal_executor.subprocess.Popen",
            return_value=process,
        ):
            result = executor.execute(
                TerminalCommand(
                    id="overflow",
                    command="python",
                    risk_level=CommandRisk.SAFE,
                )
            )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, -1)
        self.assertIn("output", result.stderr.lower())
        self.assertEqual(process.kill_calls, 1)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 10000)

    def test_stderr_overflow_kills_child_independently(self):
        executor = TerminalExecutor(
            allowed_commands=["python"],
            sandbox=False,
            allow_caller_context=True,
        )
        process = _PendingBoundedProcess(
            b"ok",
            b"e" * (8 * 1024 * 1024 + 1),
        )
        with patch(
            "core.kernel.terminal_executor.subprocess.Popen",
            return_value=process,
        ):
            result = executor.execute(
                TerminalCommand(
                    id="stderr-overflow",
                    command="python",
                    risk_level=CommandRisk.SAFE,
                )
            )

        self.assertFalse(result.success)
        self.assertIn("output", result.stderr.lower())
        self.assertEqual(process.kill_calls, 1)


class TestTerminalExecutorDeniedCommands(unittest.TestCase):
    def test_denied_command_overrides_allowed_command(self):
        ex = TerminalExecutor(
            allowed_commands=["python"],
            denied_commands=["python"],
            sandbox=False,
            allow_caller_context=True,
        )

        with patch("core.kernel.terminal_executor.subprocess.Popen") as process:
            result = ex.execute(TerminalCommand(id="denied", command="python"))

        self.assertFalse(result.success)
        self.assertIn("denied", result.stderr.lower())
        self.assertEqual(result.risk_level, CommandRisk.DANGEROUS.value)
        self.assertEqual(ex.get_audit_log(), [])
        process.assert_not_called()


class TestTerminalExecutorLifecycle(unittest.TestCase):
    def test_close_waits_for_inflight_sandbox_command_before_cleanup(self):
        executor = TerminalExecutor(max_concurrency=1)
        sandbox_dir = executor.sandbox_dir
        command_started = threading.Event()
        release_command = threading.Event()
        command_result = {}
        close_finished = threading.Event()

        def running_command(command):
            command_started.set()
            self.assertTrue(release_command.wait(timeout=5))
            return TerminalResult(
                command_id=command.id,
                exit_code=0,
                stdout="done",
                stderr="",
                duration=0.0,
                success=True,
                risk_level=command.risk_level.value,
            )

        executor._run_command = running_command
        command_thread = threading.Thread(
            target=lambda: command_result.setdefault(
                "value",
                executor.execute(TerminalCommand(id="inflight", command="echo")),
            )
        )
        close_thread = threading.Thread(
            target=lambda: (executor.close(), close_finished.set())
        )
        try:
            command_thread.start()
            self.assertTrue(command_started.wait(timeout=5))

            close_thread.start()
            close_thread.join(timeout=0.1)

            self.assertTrue(close_thread.is_alive())
            self.assertFalse(close_finished.is_set())
            self.assertTrue(sandbox_dir.is_dir())
        finally:
            release_command.set()
            command_thread.join(timeout=5)
            close_thread.join(timeout=5)
            executor.close()

        self.assertTrue(close_finished.is_set())
        self.assertTrue(command_result["value"].success)
        self.assertFalse(sandbox_dir.exists())

    def test_concurrent_close_waiters_share_one_sandbox_cleanup(self):
        executor = TerminalExecutor(max_concurrency=1)
        command_started = threading.Event()
        release_command = threading.Event()
        close_errors = []

        def running_command(command):
            command_started.set()
            self.assertTrue(release_command.wait(timeout=5))
            return TerminalResult(
                command_id=command.id,
                exit_code=0,
                stdout="done",
                stderr="",
                duration=0.0,
                success=True,
                risk_level=command.risk_level.value,
            )

        def close_executor():
            try:
                executor.close()
            except Exception as error:
                close_errors.append(error)

        executor._run_command = running_command
        command_thread = threading.Thread(
            target=lambda: executor.execute(TerminalCommand(id="inflight", command="echo"))
        )
        first_close = threading.Thread(target=close_executor)
        second_close = threading.Thread(target=close_executor)
        try:
            command_thread.start()
            self.assertTrue(command_started.wait(timeout=5))
            first_close.start()
            first_close.join(timeout=0.1)
            self.assertTrue(first_close.is_alive())
            second_close.start()
            second_close.join(timeout=0.1)
            self.assertTrue(second_close.is_alive())
        finally:
            release_command.set()
            command_thread.join(timeout=5)
            first_close.join(timeout=5)
            second_close.join(timeout=5)
            executor.close()

        self.assertEqual(close_errors, [])

    def test_cleanup_failure_keeps_sandbox_owned_for_close_retry(self):
        executor = TerminalExecutor()
        sandbox_directory = executor._sandbox_directory
        sandbox_path = executor.sandbox_dir

        with patch.object(
            sandbox_directory,
            "cleanup",
            side_effect=[OSError("sandbox is busy"), None],
        ) as cleanup:
            with self.assertRaisesRegex(OSError, "sandbox is busy"):
                executor.close()

            self.assertIs(executor._sandbox_directory, sandbox_directory)
            self.assertEqual(executor.sandbox_dir, sandbox_path)

            executor.close()

        self.assertEqual(cleanup.call_count, 2)
        self.assertIsNone(executor._sandbox_directory)
        self.assertIsNone(executor.sandbox_dir)
        sandbox_directory.cleanup()


class TestTerminalExecutorAssessRisk(unittest.TestCase):
    def test_safe_commands(self):
        ex = TerminalExecutor()
        for cmd in ["echo", "ls", "cat", "pwd", "date"]:
            self.assertEqual(ex._assess_risk(cmd), CommandRisk.SAFE)

    def test_dangerous_commands(self):
        ex = TerminalExecutor()
        for cmd in ["rm", "dd", "mkfs", "shred", "format"]:
            self.assertEqual(ex._assess_risk(cmd), CommandRisk.DANGEROUS)

    def test_moderate_commands(self):
        ex = TerminalExecutor()
        for cmd in ["mv", "cp", "touch", "mkdir"]:
            self.assertEqual(ex._assess_risk(cmd), CommandRisk.MODERATE)

    def test_unknown_returns_safe(self):
        ex = TerminalExecutor()
        self.assertEqual(ex._assess_risk("unknown_cmd_xyz"), CommandRisk.SAFE)

    def test_empty_string_returns_safe(self):
        ex = TerminalExecutor()
        self.assertEqual(ex._assess_risk(""), CommandRisk.SAFE)


class TestTerminalExecutorAuditLog(unittest.TestCase):
    def test_get_audit_log_returns_list(self):
        ex = TerminalExecutor()
        self.assertIsInstance(ex.get_audit_log(), list)

    def test_get_audit_log_respects_limit(self):
        ex = TerminalExecutor()
        for i in range(10):
            cmd = TerminalCommand(id=f"l{i}", command="echo")
            ex.execute(cmd)
        log = ex.get_audit_log(limit=3)
        self.assertEqual(len(log), 3)

    def test_clear_audit_log_empties_log(self):
        ex = TerminalExecutor()
        cmd = TerminalCommand(id="c1", command="echo")
        ex.execute(cmd)
        self.assertEqual(len(ex.get_audit_log()), 1)
        ex.clear_audit_log()
        self.assertEqual(len(ex.get_audit_log()), 0)

    def test_audit_history_evicts_oldest_entries(self):
        ex = TerminalExecutor(allowed_commands=["echo"], sandbox=False, allow_caller_context=True)
        result = TerminalResult(
            command_id="result",
            exit_code=0,
            stdout="",
            stderr="",
            duration=0.0,
            success=True,
            risk_level=CommandRisk.SAFE.value,
        )
        with patch.object(ex, "_run_command", return_value=result):
            for index in range(1005):
                ex.execute(
                    TerminalCommand(
                        id=f"executor-{index}",
                        command="echo",
                        risk_level=CommandRisk.SAFE,
                    )
                )

        audit_log = ex.get_audit_log(limit=5000)
        self.assertEqual(len(audit_log), 1000)
        self.assertEqual(audit_log[0]["command_id"], "executor-5")
        self.assertEqual(audit_log[-1]["command_id"], "executor-1004")

    def test_audit_snapshots_do_not_alias_internal_entries(self):
        ex = TerminalExecutor(allowed_commands=["echo"], sandbox=False, allow_caller_context=True)
        result = TerminalResult(
            command_id="result",
            exit_code=0,
            stdout="",
            stderr="",
            duration=0.0,
            success=True,
            risk_level=CommandRisk.SAFE.value,
        )
        with patch.object(ex, "_run_command", return_value=result):
            ex.execute(
                TerminalCommand(
                    id="audit",
                    command="echo",
                    risk_level=CommandRisk.SAFE,
                )
            )

        snapshot = ex.get_audit_log(limit=1)
        snapshot[0]["command_id"] = "tampered"
        self.assertEqual(ex.get_audit_log(limit=1)[0]["command_id"], "audit")

    def test_audit_limit_is_a_non_negative_plain_integer(self):
        ex = TerminalExecutor(sandbox=False, allow_caller_context=True)
        self.assertEqual(ex.get_audit_log(limit=0), [])
        for invalid_limit in (-1, True, 1.5, "1"):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    ex.get_audit_log(limit=invalid_limit)


class TestTerminalExecutorInitExtended(unittest.TestCase):
    def test_caller_context_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "caller context"):
            TerminalExecutor(sandbox=False)

        executor = TerminalExecutor(
            sandbox=False,
            allow_caller_context=True,
        )
        self.assertFalse(executor.sandbox)
        self.assertIsNone(executor.sandbox_dir)

    def test_caller_context_opt_in_cannot_be_combined_with_sandbox(self):
        with self.assertRaisesRegex(ValueError, "caller context"):
            TerminalExecutor(allow_caller_context=True)

    def test_default_timeout_is_30(self):
        ex = TerminalExecutor()
        self.assertEqual(ex.default_timeout, 30)

    def test_custom_timeout_is_set(self):
        ex = TerminalExecutor(default_timeout=60)
        self.assertEqual(ex.default_timeout, 60)

    def test_audit_log_starts_empty(self):
        ex = TerminalExecutor()
        self.assertEqual(ex.get_audit_log(), [])

    def test_max_output_size_default(self):
        ex = TerminalExecutor()
        self.assertEqual(ex.max_output_size, 10000)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. terminal_executor extended v2 - Iteration 55")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestTerminalExecutorExecuteShell,
        TestTerminalExecutorProcessOutput,
        TestTerminalExecutorDeniedCommands,
        TestTerminalExecutorLifecycle,
        TestTerminalExecutorAssessRisk,
        TestTerminalExecutorAuditLog,
        TestTerminalExecutorInitExtended,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_all_tests())
