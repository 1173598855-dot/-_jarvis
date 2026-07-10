"""Extended tests v2 for terminal_executor.py - Iteration 55"""
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.terminal_executor import (
    CommandRisk,
    TerminalCommand,
    TerminalExecutor,
)


class TestTerminalExecutorExecuteShell(unittest.TestCase):
    def test_empty_shell_returns_error(self):
        ex = TerminalExecutor()
        result = ex.execute_shell("")
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, -1)

    def test_shell_echo_succeeds(self):
        ex = TerminalExecutor()
        result = ex.execute_shell("echo hello")
        self.assertTrue(result.success)
        self.assertIn("hello", result.stdout)

    def test_shell_with_custom_timeout(self):
        ex = TerminalExecutor(default_timeout=5)
        result = ex.execute_shell("echo quick")
        self.assertTrue(result.success)


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


class TestTerminalExecutorInitExtended(unittest.TestCase):
    def test_default_timeout_is_30(self):
        ex = TerminalExecutor()
        self.assertEqual(ex.default_timeout, 30)

    def test_custom_timeout_is_set(self):
        ex = TerminalExecutor(default_timeout=60)
        self.assertEqual(ex.default_timeout, 60)

    def test_has_audit_log_list(self):
        ex = TerminalExecutor()
        self.assertIsInstance(ex._audit_log, list)

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
