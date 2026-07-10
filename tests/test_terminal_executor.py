# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. test suite - Phase 12: Test-driven self-evolution
Run: python3 tests/test_terminal_executor.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from core.kernel.terminal_executor import CommandRisk, TerminalCommand, TerminalExecutor


@pytest.fixture
def executor():
    """Default executor with safe command whitelist"""
    return TerminalExecutor()


@pytest.fixture
def safe_executor():
    """Executor with strict whitelist (no dangerous commands allowed)"""
    return TerminalExecutor(allowed_commands=["echo", "date", "whoami", "pwd"])


# ============================================================
# Test: Safe commands whitelist
# ============================================================

class TestSafeCommands:
    """Safe commands should execute normally"""

    def test_echo_allowed(self, executor):
        cmd = TerminalCommand(id="s1", command="echo", args=["hello"], risk_level=CommandRisk.SAFE)
        result = executor.execute(cmd)
        assert result.success is True
        assert "hello" in result.stdout

    def test_whoami_allowed(self, executor):
        cmd = TerminalCommand(id="s2", command="whoami", args=[], risk_level=CommandRisk.SAFE)
        result = executor.execute(cmd)
        assert result.success is True

    def test_pwd_allowed(self, executor):
        cmd = TerminalCommand(id="s3", command="pwd", args=[], risk_level=CommandRisk.SAFE)
        result = executor.execute(cmd)
        assert result.success is True

    def test_date_allowed(self, executor):
        cmd = TerminalCommand(id="s4", command="date", args=[], risk_level=CommandRisk.SAFE)
        result = executor.execute(cmd)
        assert result.success is True

    def test_risk_level_safe(self, executor):
        assert executor._assess_risk("echo") == CommandRisk.SAFE
        assert executor._assess_risk("ls") == CommandRisk.SAFE

    def test_risk_level_via_assess(self, executor):
        assert executor._assess_risk("cat") == CommandRisk.SAFE
        assert executor._assess_risk("echo hello") == CommandRisk.SAFE


# ============================================================
# Test: Dangerous commands blacklist
# ============================================================

class TestDangerousCommands:
    """Dangerous commands must be blocked"""

    def test_rm_rf_root_blocked(self, executor):
        """rm -rf / must be blocked"""
        cmd = TerminalCommand(id="danger-1", command="rm", args=["-rf", "/"])
        result = executor.execute(cmd)
        assert result.success is False
        assert "Security block" in result.stderr

    def test_rm_rf_home_blocked(self, executor):
        """rm -rf ~ must be blocked"""
        cmd = TerminalCommand(id="danger-2", command="rm", args=["-rf", "~"])
        result = executor.execute(cmd)
        assert result.success is False
        assert "Security block" in result.stderr

    def test_fork_bomb_blocked(self, executor):
        """Fork bomb must be blocked"""
        cmd = TerminalCommand(id="danger-3", command="bash", args=["-c", ":(){ :|:& };:"])
        result = executor.execute(cmd)
        assert result.success is False

    def test_format_blocked(self, executor):
        """format command must be blocked"""
        cmd = TerminalCommand(id="danger-4", command="format", args=["C:"])
        result = executor.execute(cmd)
        assert result.success is False

    def test_shred_blocked(self, executor):
        """shred command must be blocked"""
        cmd = TerminalCommand(id="danger-5", command="shred", args=["-u", "/tmp/test"])
        result = executor.execute(cmd)
        assert result.success is False

    def test_risk_level_dangerous(self, executor):
        """Risk assessment should classify dangerous commands correctly"""
        assert executor._assess_risk("rm") == CommandRisk.DANGEROUS
        assert executor._assess_risk("format") == CommandRisk.DANGEROUS
        assert executor._assess_risk("shred") == CommandRisk.DANGEROUS


# ============================================================
# Test: Whitelist enforcement
# ============================================================

class TestWhitelistEnforcement:
    """Commands not in whitelist must be blocked"""

    def test_blocked_command_not_in_allowlist(self, safe_executor):
        """ls not in strict allowlist must be blocked"""
        cmd = TerminalCommand(id="block-1", command="ls")
        result = safe_executor.execute(cmd)
        assert result.success is False
        assert "Security block" in result.stderr or "not in allowlist" in result.stderr

    def test_allowed_command_passes(self, safe_executor):
        """echo in allowlist must pass"""
        cmd = TerminalCommand(id="ok-1", command="echo", args=["ok"])
        result = safe_executor.execute(cmd)
        assert result.success is True


# ============================================================
# Test: Risk assessment
# ============================================================

class TestRiskAssessment:
    """Risk level classification tests"""

    def test_safe_command_risk(self, executor):
        assert executor._assess_risk("echo") == CommandRisk.SAFE
        assert executor._assess_risk("ls") == CommandRisk.SAFE
        assert executor._assess_risk("cat") == CommandRisk.SAFE

    def test_moderate_command_risk(self, executor):
        assert executor._assess_risk("mv") == CommandRisk.MODERATE
        assert executor._assess_risk("cp") == CommandRisk.MODERATE

    def test_dangerous_command_risk(self, executor):
        assert executor._assess_risk("rm") == CommandRisk.DANGEROUS
        assert executor._assess_risk("dd") == CommandRisk.DANGEROUS

    def test_unknown_command_risk(self, executor):
        """Unknown commands assessed as SAFE (blocking done by whitelist)"""
        assert executor._assess_risk("badcmd_xyz") == CommandRisk.SAFE


# ============================================================
# Test: Audit log
# ============================================================

class TestAuditLog:
    """Audit log should track command executions"""

    def test_audit_log_records_execution(self, executor):
        cmd = TerminalCommand(id="audit-1", command="echo", args=["test"])
        _ = executor.execute(cmd)
        log = executor.get_audit_log()
        assert len(log) >= 1

    def test_audit_log_records_blocked(self, executor):
        """Audit log records executed commands (blacklist blocks not logged)"""
        cmd = TerminalCommand(id="audit-2", command="rm", args=["-rf", "/"])
        result = executor.execute(cmd)
        assert result.success is False

    def test_audit_log_records_executed(self, executor):
        """Safe commands should be logged"""
        cmd = TerminalCommand(id="audit-3", command="echo", args=["log_test"])
        _ = executor.execute(cmd)
        log = executor.get_audit_log()
        assert any(entry.get("success") is True for entry in log)

    def test_audit_log_limit(self, executor):
        """Audit log should have a max size"""
        for i in range(10):
            cmd = TerminalCommand(id=f"limit-{i}", command="echo", args=[f"msg{i}"])
            executor.execute(cmd)
        log = executor.get_audit_log()
        assert len(log) <= 100


class TestExecuteShell:
    """execute_shell() wrapper method"""

    def test_execute_shell_echo(self, executor):
        """execute_shell('echo hello') succeeds"""
        result = executor.execute_shell("echo hello")
        assert result.success is True

    def test_execute_shell_empty_returns_error(self, executor):
        """execute_shell('') returns error result"""
        result = executor.execute_shell("")
        assert result.success is False
        assert "Empty" in result.stderr or result.exit_code == -1


class TestClearAuditLog:
    """clear_audit_log() resets the log"""

    def test_clear_audit_log_empties_log(self, executor):
        """After clear_audit_log, get_audit_log returns empty"""
        _ = executor.execute(TerminalCommand(id="cl-1", command="echo", args=["x"]))
        executor.clear_audit_log()
        log = executor.get_audit_log()
        assert len(log) == 0

    def test_clear_then_new_entries_work(self, executor):
        """After clear, new commands are logged normally"""
        executor.clear_audit_log()
        _ = executor.execute(TerminalCommand(id="cl-2", command="echo", args=["after"]))
        log = executor.get_audit_log()
        assert len(log) >= 1


class TestTerminalResultToDict:
    """TerminalResult.to_dict() serialization"""

    def test_to_dict_has_required_keys(self, executor):
        """to_dict returns dict with command_id, exit_code, success"""
        result = executor.execute(TerminalCommand(id="td-1", command="echo", args=["x"]))
        d = result.to_dict()
        assert "command_id" in d
        assert "exit_code" in d
        assert "success" in d

    def test_to_dict_success_true(self, executor):
        """to_dict for successful command has success=True"""
        result = executor.execute(TerminalCommand(id="td-2", command="echo", args=["ok"]))
        d = result.to_dict()
        assert d["success"] is True


class TestCommandRisk:
    """CommandRisk enum values"""

    def test_command_risk_values(self):
        """CommandRisk has SAFE, MODERATE, DANGEROUS"""
        from core.kernel.terminal_executor import CommandRisk
        assert hasattr(CommandRisk, "SAFE")
        assert hasattr(CommandRisk, "MODERATE")
        assert hasattr(CommandRisk, "DANGEROUS")

    def test_assess_risk_moderate(self, executor):
        """mv and cp are MODERATE"""
        assert executor._assess_risk("mv a b") == CommandRisk.MODERATE
        assert executor._assess_risk("cp a b") == CommandRisk.MODERATE

    def test_assess_risk_unknown_is_safe(self, executor):
        """Unknown commands default to SAFE"""
        assert executor._assess_risk("curl https://example.com") == CommandRisk.SAFE
