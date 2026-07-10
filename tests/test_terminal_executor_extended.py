"""Extended tests for terminal_executor.py - Iteration 46"""
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.terminal_executor import (
    CommandRisk,
    TerminalCommand,
    TerminalExecutor,
    TerminalResult,
)


class TestTerminalCommandDataclass(unittest.TestCase):
    def test_defaults(self):
        cmd = TerminalCommand(id="c1", command="echo hello")
        self.assertEqual(cmd.args, [])
        self.assertIsNone(cmd.cwd)
        self.assertEqual(cmd.timeout, 30)
        self.assertEqual(cmd.risk_level, CommandRisk.MODERATE)

    def test_custom_fields(self):
        cmd = TerminalCommand(id="c2", command="ls", args=["-la"],
                             cwd="/tmp", timeout=10,
                             risk_level=CommandRisk.SAFE)
        self.assertEqual(cmd.args, ["-la"])
        self.assertEqual(cmd.cwd, "/tmp")


class TestTerminalResultToDict(unittest.TestCase):
    def test_to_dict_keys(self):
        r = TerminalResult(command_id="c1", exit_code=0,
                         stdout="out", stderr="err",
                         duration=0.1, success=True, risk_level="safe")
        d = r.to_dict()
        for key in ["command_id", "exit_code", "duration", "timestamp"]:
            self.assertIn(key, d)

    def test_to_dict_stdout_truncated(self):
        r = TerminalResult(command_id="c1", exit_code=0,
                         stdout="x" * 10000,
                         stderr="", duration=0.1, success=True, risk_level="safe")
        d = r.to_dict()
        self.assertLessEqual(len(d["stdout"]), 5000)


class TestTerminalExecutorDangerousPatterns(unittest.TestCase):
    def _exe(self):
        return TerminalExecutor(sandbox=False)

    def test_block_rm_rf_root(self):
        r = self._exe().execute(TerminalCommand(id="c", command="rm -rf /",
                              risk_level=CommandRisk.DANGEROUS))
        self.assertFalse(r.success)
        self.assertIn("Security block", r.stderr)

    def test_block_rm_rf_home(self):
        r = self._exe().execute(TerminalCommand(id="c", command="rm -rf ~",
                              risk_level=CommandRisk.DANGEROUS))
        self.assertFalse(r.success)

    def test_block_mkfs(self):
        r = self._exe().execute(TerminalCommand(id="c", command="mkfs /dev/sda",
                              risk_level=CommandRisk.DANGEROUS))
        self.assertFalse(r.success)

    def test_block_dd_if(self):
        r = self._exe().execute(TerminalCommand(id="c",
                              command="dd if=/dev/zero of=/dev/sda",
                              risk_level=CommandRisk.DANGEROUS))
        self.assertFalse(r.success)

    def test_block_fork_bomb(self):
        r = self._exe().execute(TerminalCommand(id="c",
                              command=":(){ :|:& };:",
                              risk_level=CommandRisk.DANGEROUS))
        self.assertFalse(r.success)

    def test_safe_echo_not_blocked(self):
        r = self._exe().execute(TerminalCommand(id="c", command="echo hello",
                              risk_level=CommandRisk.SAFE))
        self.assertNotIn("Security block", r.stderr)


class TestTerminalExecutorAllowlist(unittest.TestCase):
    def test_unknown_command_blocked(self):
        exe = TerminalExecutor(allowed_commands={"echo","ls"}, sandbox=False)
        r = exe.execute(TerminalCommand(id="c", command="bad_cmd",
                              risk_level=CommandRisk.MODERATE))
        self.assertFalse(r.success)
        self.assertIn("not in allowlist", r.stderr)

    def test_known_command_passes_allowlist(self):
        exe = TerminalExecutor(allowed_commands={"echo","ls"}, sandbox=False)
        r = exe.execute(TerminalCommand(id="c", command="echo hello",
                              risk_level=CommandRisk.SAFE))
        self.assertNotIn("not in allowlist", r.stderr)


class TestTerminalExecutorConcurrency(unittest.TestCase):
    def test_concurrency_limit_blocks(self):
        exe = TerminalExecutor(max_concurrency=1, sandbox=False)
        exe._running_count = 1
        r = exe.execute(TerminalCommand(id="c", command="echo",
                              risk_level=CommandRisk.SAFE))
        self.assertFalse(r.success)


class TestTerminalExecutorCwd(unittest.TestCase):
    def test_invalid_cwd(self):
        exe = TerminalExecutor(sandbox=False)
        r = exe.execute(TerminalCommand(id="c", command="echo",
                              cwd="/nonexistent_path_xyz",
                              risk_level=CommandRisk.SAFE))
        self.assertFalse(r.success)


class TestTerminalExecutorAuditLog(unittest.TestCase):
    def test_audit_log_records_execution(self):
        exe = TerminalExecutor(sandbox=False)
        self.assertEqual(len(exe._audit_log), 0)
        exe.execute(TerminalCommand(id="c1", command="echo",
                            risk_level=CommandRisk.SAFE))
        self.assertGreaterEqual(len(exe._audit_log), 1)

    def test_audit_log_has_keys(self):
        exe = TerminalExecutor(sandbox=False)
        exe.execute(TerminalCommand(id="c1", command="echo test",
                            risk_level=CommandRisk.SAFE))
        entry = exe._audit_log[-1]
        for key in ["command_id", "command", "risk_level", "success"]:
            self.assertIn(key, entry)


class TestTerminalExecutorSafeCommands(unittest.TestCase):
    def test_safe_commands_set(self):
        exe = TerminalExecutor(sandbox=False)
        for name in ["echo", "ls", "python3", "git"]:
            self.assertIn(name, exe.SAFE_COMMANDS)

    def test_dangerous_patterns_list(self):
        exe = TerminalExecutor(sandbox=False)
        self.assertGreater(len(exe.DANGEROUS_PATTERNS), 0)


class TestTerminalExecutorEnvInjection(unittest.TestCase):
    def test_custom_env_passed(self):
        import unittest.mock as um
        exe = TerminalExecutor(sandbox=False)
        with um.patch("subprocess.Popen") as mp:
            mp.return_value.communicate.return_value = ("out", "")
            mp.return_value.returncode = 0
            exe.execute(TerminalCommand(id="c", command="echo",
                                env={"MY_VAR": "my_val"},
                                risk_level=CommandRisk.SAFE))
            self.assertIn("env", mp.call_args[1])


class TestTerminalExecutorDurationCalculation(unittest.TestCase):
    def test_duration_is_float(self):
        exe = TerminalExecutor(sandbox=False)
        r = exe.execute(TerminalCommand(id="c", command="echo",
                              risk_level=CommandRisk.SAFE))
        self.assertIsInstance(r.duration, float)
        self.assertGreaterEqual(r.duration, 0)


class TestTerminalExecutorRiskLevelMapping(unittest.TestCase):
    def test_risk_level_values(self):
        self.assertEqual(CommandRisk.SAFE.value, "safe")
        self.assertEqual(CommandRisk.DANGEROUS.value, "dangerous")


class TestTerminalExecutorOutputTruncation(unittest.TestCase):
    def test_audit_log_command_truncated(self):
        exe = TerminalExecutor(sandbox=False)
        long_cmd = "echo " + "x" * 500
        exe.execute(TerminalCommand(id="c", command=long_cmd,
                              risk_level=CommandRisk.SAFE))
        entry = exe._audit_log[-1]
        self.assertLessEqual(len(entry["command"]), 200)


def run_all_tests():
    print("============================================================")
    print("J.A.R.V.I.S. terminal_executor extended tests - Iteration 46")
    print("============================================================")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestTerminalCommandDataclass, TestTerminalResultToDict,
        TestTerminalExecutorDangerousPatterns,
        TestTerminalExecutorAllowlist,
        TestTerminalExecutorConcurrency,
        TestTerminalExecutorCwd,
        TestTerminalExecutorAuditLog,
        TestTerminalExecutorSafeCommands,
        TestTerminalExecutorEnvInjection,
        TestTerminalExecutorDurationCalculation,
        TestTerminalExecutorRiskLevelMapping,
        TestTerminalExecutorOutputTruncation,
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
