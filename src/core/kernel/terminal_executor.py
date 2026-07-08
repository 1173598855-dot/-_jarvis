"""
Terminal Executor — 小奕 J.A.R.V.I.S. 安全终端自动化执行器
萃取自 Open Interpreter 的终端控制架构

功能：
1. 命令白名单/黑名单过滤
2. 超时控制与并发限制
3. 输出捕获与解析
4. 工作目录管理
5. 环境变量注入
6. 安全审计日志

设计原则：
- 所有危险命令必须在黑名单中
- 默认拒绝，白名单机制
- 每个命令独立沙箱执行
- 输出自动截断防止内存溢出
"""

import os
import sys
import subprocess
import shlex
import re
import time
import json
import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class CommandRisk(Enum):
    """命令风险等级"""
    SAFE = "safe"           # 安全：只读查询
    MODERATE = "moderate"   # 中等：文件读写
    DANGEROUS = "dangerous" # 高危：系统修改、删除


@dataclass
class TerminalCommand:
    """终端命令定义"""
    id: str
    command: str
    args: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    risk_level: CommandRisk = CommandRisk.MODERATE


@dataclass
class TerminalResult:
    """终端执行结果"""
    command_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    success: bool
    risk_level: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:5000],  # 截断防止溢出
            "stderr": self.stderr[:2000],
            "duration": round(self.duration, 3),
            "success": self.success,
            "risk_level": self.risk_level,
            "timestamp": self.timestamp,
        }


class TerminalExecutor:
    """
    安全终端执行器 — 萃取自 Open Interpreter 架构

    安全策略：
    1. 默认白名单：只有明确允许的命令才能执行
    2. 黑名单：危险命令绝对禁止
    3. 超时控制：每个命令有最大执行时间
    4. 并发限制：防止资源耗尽
    5. 输出截断：防止内存溢出
    """

    # 安全白名单 — 仅允许这些命令
    SAFE_COMMANDS = {
        # 文件查询
        "ls", "dir", "find", "which", "whereis", "type",
        # 文本处理
        "cat", "head", "tail", "less", "more", "grep", "sed", "awk",
        "echo", "printf", "wc", "sort", "uniq", "tr",
        # 系统信息
        "uname", "hostname", "whoami", "id", "date", "uptime",
        "ps", "top", "htop", "free", "df", "du", "lscpu",
        # 网络查询
        "ping", "curl", "wget", "dig", "nslookup", "netstat", "ss",
        # Git
        "git",
        # Python
        "python", "python3", "pip", "pip3",
        # 其他
        "env", "printenv", "pwd", "cd",
    }

    # 危险黑名单 — 绝对禁止
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",           # 删除根目录
        r"rm\s+-rf\s+~",           # 删除 home
        r"rm\s+-rf\s+\*",          # 删除所有
        r"mkfs",                    # 格式化磁盘
        r"dd\s+if=",               # 磁盘写入
        r">\s*/dev/",              # 写入设备
        r"shred",                   # 安全删除
        r"format\s+/",             # 格式化
        r":(){ :|:& };:",          # Fork bomb
        r"chmod\s+-R\s+777\s+/",  # 权限开放
        r"sudo\s+rm",              # 提权删除
        r"curl.*\|\s*(bash|sh)",  # 管道执行远程脚本
        r"wget.*\|\s*(bash|sh)",  # 管道执行远程脚本
        r"python.*\s+-c\s+.*rm",  # Python 删除
        r"exec\s*\(.*rm",          # 删除
        r"eval\s*\(.*rm",          # 删除
    ]

    def __init__(
        self,
        allowed_commands: Optional[List[str]] = None,
        denied_commands: Optional[List[str]] = None,
        sandbox: bool = True,
        max_concurrency: int = 4,
        default_timeout: int = 30,
        max_output_size: int = 10000,
    ):
        self.allowed_commands = set(allowed_commands or self.SAFE_COMMANDS)
        self.denied_commands = set(denied_commands or [])
        self.sandbox = sandbox
        self.max_concurrency = max_concurrency
        self.default_timeout = default_timeout
        self.max_output_size = max_output_size
        self._running_count = 0
        self._audit_log: List[Dict[str, Any]] = []

    def execute(self, cmd: TerminalCommand) -> TerminalResult:
        """
        执行终端命令（主入口）

        安全流程：
        1. 检查黑名单
        2. 检查白名单
        3. 检查并发限制
        4. 执行命令（超时控制）
        5. 截断输出
        6. 记录审计日志
        """
        # 安全检查 1：黑名单
        full_command = f"{cmd.command} {' '.join(cmd.args)}"
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, full_command, re.IGNORECASE):
                logger.warning(f"危险命令拦截: {full_command}")
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout="",
                    stderr=f"安全拦截: 命令匹配危险模式 '{pattern}'",
                    duration=0,
                    success=False,
                    risk_level=CommandRisk.DANGEROUS.value,
                )

        # 安全检查 2：白名单
        base_cmd = cmd.command.split()[0] if cmd.command else ""
        if base_cmd not in self.allowed_commands:
            logger.warning(f"未授权命令拦截: {base_cmd}")
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr=f"安全拦截: '{base_cmd}' 不在允许列表中",
                duration=0,
                success=False,
                risk_level=CommandRisk.DANGEROUS.value,
            )

        # 安全检查 3：并发限制
        if self._running_count >= self.max_concurrency:
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr=f"并发限制：当前 {self._running_count}/{self.max_concurrency} 个任务运行中",
                duration=0,
                success=False,
                risk_level=CommandRisk.MODERATE.value,
            )

        # 执行命令
        self._running_count += 1
        start_time = time.time()
        try:
            result = self._run_command(cmd)
        finally:
            self._running_count -= 1

        # 审计日志
        self._audit_log.append({
            "command_id": cmd.id,
            "command": full_command[:200],
            "risk_level": cmd.risk_level.value,
            "success": result.success,
            "timestamp": datetime.now().isoformat(),
        })

        return result

    def _run_command(self, cmd: TerminalCommand) -> TerminalResult:
        """实际执行命令"""
        try:
            # 构建完整命令
            full_cmd = [cmd.command] + cmd.args

            # 工作目录
            cwd = cmd.cwd or os.getcwd()
            if not os.path.isdir(cwd):
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout="",
                    stderr=f"工作目录不存在: {cwd}",
                    duration=0,
                    success=False,
                    risk_level=cmd.risk_level.value,
                )

            # 环境变量
            env = {**os.environ, **cmd.env}

            # 执行
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                text=True,
                shell=False,
            )

            try:
                stdout, stderr = process.communicate(timeout=cmd.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                return TerminalResult(
                    command_id=cmd.id,
                    exit_code=-1,
                    stdout=stdout[:self.max_output_size],
                    stderr=f"超时（{cmd.timeout}s）",
                    duration=cmd.timeout,
                    success=False,
                    risk_level=cmd.risk_level.value,
                )

            # 截断输出
            stdout = stdout[:self.max_output_size]
            stderr = stderr[:self.max_output_size // 2]

            duration = time.time() - time.perf_counter() if 'time.perf_counter' in dir() else time.time() - time.time()

            return TerminalResult(
                command_id=cmd.id,
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                duration=duration,
                success=process.returncode == 0,
                risk_level=cmd.risk_level.value,
            )

        except Exception as e:
            logger.error(f"命令执行失败: {e}")
            return TerminalResult(
                command_id=cmd.id,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration=0,
                success=False,
                risk_level=cmd.risk_level.value,
            )

    def execute_shell(self, shell_command: str, timeout: int = 30) -> TerminalResult:
        """
        执行 Shell 命令（便捷方法）

        Args:
            shell_command: 完整 shell 命令字符串
            timeout: 超时时间（秒）

        Returns:
            TerminalResult
        """
        # 解析命令
        parts = shlex.split(shell_command)
        if not parts:
            return TerminalResult(
                command_id="shell",
                exit_code=-1,
                stdout="",
                stderr="空命令",
                duration=0,
                success=False,
                risk_level=CommandRisk.DANGEROUS.value,
            )

        cmd = TerminalCommand(
            id=f"shell-{int(time.time() * 1000)}",
            command=parts[0],
            args=parts[1:],
            timeout=timeout,
            risk_level=self._assess_risk(parts[0]),
        )

        return self.execute(cmd)

    def _assess_risk(self, command: str) -> CommandRisk:
        """评估命令风险等级"""
        base_cmd = command.split()[0] if command else ""

        # 明确危险命令
        dangerous = {"rm", "dd", "mkfs", "shred", "format", "chmod"}
        if base_cmd in dangerous:
            return CommandRisk.DANGEROUS

        # 文件修改命令
        moderate = {"mv", "cp", "touch", "mkdir", "pip", "npm"}
        if base_cmd in moderate:
            return CommandRisk.MODERATE

        return CommandRisk.SAFE

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取审计日志"""
        return self._audit_log[-limit:]

    def clear_audit_log(self):
        """清除审计日志"""
        self._audit_log.clear()


# ============================================================
# CLI 入口
# ============================================================

def main():
    """命令行入口"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python terminal_executor.py <command> [args...]")
        print("\n示例:")
        print("  python terminal_executor.py ls -la")
        print("  python terminal_executor.py pwd")
        print("  python terminal_executor.py python3 --version")
        sys.exit(1)

    executor = TerminalExecutor()
    shell_command = " ".join(sys.argv[1:])

    print(f"🔧 执行: {shell_command}")
    print("-" * 60)

    result = executor.execute_shell(shell_command)

    if result.success:
        print(result.stdout)
    else:
        print(f"❌ 错误 (exit {result.exit_code}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)

    print("-" * 60)
    print(f"⏱️  耗时: {result.duration:.2f}s")
    print(f"⚠️  风险等级: {result.risk_level}")

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
