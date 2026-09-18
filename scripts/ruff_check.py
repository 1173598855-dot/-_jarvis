#!/usr/bin/env python3
"""
ruff_check.py — 小奕 J.A.R.V.I.S. 代码质量检查脚本

功能：
1. 自动检测 ruff 是否已安装（`ruff --version`），未安装时给出安装提示
2. 对 src/ 目录运行 ruff check（Lint）+ ruff format --check（格式检查）
3. 输出结构化结果：问题文件数、问题总数、严重级别分布
4. 退出码：0=通过，1=有问题，2=ruff 未安装
5. 支持 --fix 参数自动修复

使用方式：
    python scripts/ruff_check.py              # 检查模式
    python scripts/ruff_check.py --fix         # 自动修复模式
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

# ── 配置 ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
REPORT_FILE = PROJECT_ROOT / "scripts" / "ruff_report.json"

# ruff 退出码映射：
# 0 = 无问题
# 1 = 发现 lint/format 问题
# 2 = 内部错误（如配置文件问题）
# 123 = ruff 内部异常
NON_ISSUE_EXIT_CODES = {0, 2, 123}
_MAX_RUFF_OUTPUT_BYTES = 8 * 1024 * 1024
_RUFF_READ_CHUNK_BYTES = 64 * 1024


def _ruff_command() -> list[str]:
    ruff_path = shutil.which("ruff")
    if ruff_path:
        return [ruff_path]
    if sys.executable:
        return [sys.executable, "-m", "ruff"]
    return ["ruff"]


def _decode_process_output(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value or "")


def _read_bounded_process_stream(
    stream: object,
    limit: int,
    chunks: list[bytes],
    overflow: threading.Event,
) -> None:
    total = 0
    try:
        while not overflow.is_set():
            chunk = stream.read(_RUFF_READ_CHUNK_BYTES)
            if not chunk:
                return
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            elif not isinstance(chunk, bytes):
                chunk = bytes(chunk)
            next_total = total + len(chunk)
            if next_total > limit:
                retained = limit - total
                if retained > 0:
                    chunks.append(chunk[:retained])
                overflow.set()
                return
            chunks.append(chunk)
            total = next_total
    except (OSError, TypeError, ValueError):
        return


def _bounded_process_communicate(
    process: object,
    *,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int,
) -> tuple[bytes, bytes, bool, bool]:
    """Collect both Ruff streams without retaining output beyond raw limits."""
    stdout_stream = getattr(process, "stdout", None)
    stderr_stream = getattr(process, "stderr", None)
    if not callable(getattr(stdout_stream, "read", None)) or not callable(
        getattr(stderr_stream, "read", None)
    ):
        return b"", b"", False, True

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    overflow = threading.Event()
    stdout_reader = threading.Thread(
        target=_read_bounded_process_stream,
        args=(stdout_stream, stdout_limit, stdout_chunks, overflow),
        daemon=True,
    )
    stderr_reader = threading.Thread(
        target=_read_bounded_process_stream,
        args=(stderr_stream, stderr_limit, stderr_chunks, overflow),
        daemon=True,
    )
    stdout_reader.start()
    stderr_reader.start()

    deadline = time.monotonic() + timeout
    timed_out = False
    killed = False

    def kill_once() -> None:
        nonlocal killed
        if killed:
            return
        killed = True
        try:
            process.kill()
        except (OSError, AttributeError):
            pass

    while True:
        if overflow.is_set():
            kill_once()
            break
        if process.poll() is not None:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            kill_once()
            break
        try:
            process.wait(timeout=min(remaining, 0.05))
        except subprocess.TimeoutExpired:
            continue
        except (OSError, ValueError):
            break

    if killed:
        try:
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    stdout_reader.join(timeout=1.0)
    stderr_reader.join(timeout=1.0)
    for stream in (stdout_stream, stderr_stream):
        try:
            stream.close()
        except (OSError, AttributeError, ValueError):
            pass

    return (
        b"".join(stdout_chunks),
        b"".join(stderr_chunks),
        timed_out,
        overflow.is_set(),
    )


def _run_bounded_command(
    command: list[str],
    *,
    cwd: Path | None,
    timeout: float,
) -> tuple[int, str, str]:
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr, timed_out, output_limited = _bounded_process_communicate(
            process,
            timeout=timeout,
            stdout_limit=_MAX_RUFF_OUTPUT_BYTES,
            stderr_limit=_MAX_RUFF_OUTPUT_BYTES,
        )
    except subprocess.TimeoutExpired:
        return -1, "", f"ruff 执行超时（{timeout:g}s）"
    except FileNotFoundError:
        return -1, "", "ruff 命令未找到"
    except Exception as error:
        return -1, "", f"执行异常: {error}"

    if output_limited:
        return -1, "", f"ruff output exceeds {_MAX_RUFF_OUTPUT_BYTES} bytes"
    if timed_out:
        return -1, "", f"ruff 执行超时（{timeout:g}s）"
    return (
        process.returncode if process.returncode is not None else -1,
        _decode_process_output(stdout),
        _decode_process_output(stderr),
    )


def check_ruff_installed() -> str | None:
    """检测 ruff 是否可用，返回版本字符串或 None。"""
    code, stdout, _stderr = _run_bounded_command(
        _ruff_command() + ["--version"], cwd=PROJECT_ROOT, timeout=10
    )
    if code == 0:
        return stdout.strip()

    return None


def run_ruff_command(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """执行 ruff 命令，返回 (exit_code, stdout, stderr)。"""
    return _run_bounded_command(_ruff_command() + args, cwd=cwd, timeout=120)


def parse_ruff_output(output: str) -> list[dict]:
    """解析 ruff --output-format=json 的输出，返回问题列表。"""
    issues = []
    try:
        data = json.loads(output)
        if isinstance(data, list):
            for item in data:
                issues.append({
                    "file": item.get("file", ""),
                    "line": item.get("start_row", 0),
                    "column": item.get("start_column", 0),
                    "code": item.get("code", ""),
                    "message": item.get("message", ""),
                    "rule": item.get("rule_id", item.get("code", "")),
                    "severity": classify_severity(item.get("code", "")),
                    "source": item.get("source", ""),
                })
    except (json.JSONDecodeError, ValueError):
        # 如果输出不是 JSON，尝试按行解析文本格式
        for line in output.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("Found"):
                continue
            # 典型文本格式：path:line:col: CODE message
            match = re.match(
                r"(.+):(\d+):(\d+):\s+([A-Z]\d+)\s+(.+)$", line
            )
            if match:
                code = match.group(4)
                issues.append({
                    "file": match.group(1),
                    "line": int(match.group(2)),
                    "column": int(match.group(3)),
                    "code": code,
                    "message": match.group(5),
                    "rule": code,
                    "severity": classify_severity(code),
                    "source": line,
                })

    return issues


def classify_severity(code: str) -> str:
    """根据 ruff 规则前缀分类严重级别。"""
    if not code:
        return "unknown"
    prefix = code[0].upper()
    severity_map = {
        "E": "error",       # pycodestyle errors
        "F": "error",       # pyflakes
        "W": "warning",     # pycodestyle warnings
        "I": "info",        # isort
        "N": "info",        # pep8-naming
        "D": "info",        # pydocstyle
        "S": "warning",     # bandit (security)
        "UP": "info",       # pyupgrade
        "B": "warning",     # flake8-bugbear
        "C": "info",        # mccabe, comprehensions
        "R": "info",        # refurb
        "T": "info",        # flake8-type-checking
        "Q": "info",        # flake8-quotes
        "A": "info",        # flake8-builtins
        "YTT": "info",      # flake8-2020
        "FBT": "info",      # flake8-boolean-trap
        "C4": "info",       # flake8-comprehensions
        "DTZ": "warning",   # flake8-datetimez
        "T10": "warning",   # flake8-debugger
        "EM": "error",      # flake8-errmsg
        "EXE": "warning",   # flake8-executable
        "FIX": "info",      # flake8-fixme
        "ICN": "info",      # flake8-import-conventions
        "INP": "info",      # flake8-no-pep420
        "ISC": "info",      # flake8-implicit-str-concat
        "NPY": "info",      # NumPy-specific rules
        "PD": "info",       # pandas-vet
        "PGH": "warning",   # pygrep-hooks
        "PIE": "info",      # flake8-pie
        "PL": "warning",    # Pylint
        "PT": "info",       # flake8-pytest-style
        "PTH": "info",      # flake8-use-pathlib
        "PYI": "info",      # flake8-pyi
        "RSE": "warning",   # flake8-raise
        "RET": "warning",   # flake8-return
        "RUF": "info",      # Ruff-specific rules
        "SIM": "info",      # flake8-simplify
        "SLF": "info",      # flake8-self
        "TCH": "info",      # flake8-type-checking
        "TRY": "warning",   # tryceratops
        "WPS": "warning",   # wemake-python-styleguide
        "PERF": "info",     # perflint
    }
    return severity_map.get(prefix, "info")


def run_checks(src_dir: Path, fix_mode: bool = False) -> dict:
    """运行 ruff lint + format 检查，返回结构化结果。"""
    result = {
        "ruff_available": True,
        "ruff_version": "",
        "mode": "fix" if fix_mode else "check",
        "src_directory": str(src_dir),
        "lint_exit_code": None,
        "format_exit_code": None,
        "lint_issues": [],
        "format_issues": [],
        "files_with_issues": 0,
        "total_issues": 0,
        "severity_distribution": {},
        "fixed_count": 0,
    }

    # 1. 检测 ruff
    version = check_ruff_installed()
    if version is None:
        result["ruff_available"] = False
        return result

    result["ruff_version"] = version

    # 确保 src 目录存在
    if not src_dir.is_dir():
        result["error"] = f"源目录不存在: {src_dir}"
        return result

    # 2. ruff check
    check_args = ["check", str(src_dir), "--output-format=json", "--show-source"]
    if fix_mode:
        check_args.insert(1, "--fix")

    lint_code, lint_stdout, lint_stderr = run_ruff_command(check_args, PROJECT_ROOT)
    result["lint_exit_code"] = lint_code

    if lint_code not in NON_ISSUE_EXIT_CODES and lint_code != -1:
        # 内部错误
        result["lint_error"] = lint_stderr or lint_stdout or f"ruff check 异常退出码: {lint_code}"

    # 解析 lint 结果
    lint_issues = parse_ruff_output(lint_stdout)
    result["lint_issues"] = lint_issues

    # 3. ruff format --check
    format_args = [
        "format",
        str(src_dir),
        "--check",
        "--diff",
    ]
    format_code, format_stdout, format_stderr = run_ruff_command(
        format_args, PROJECT_ROOT
    )
    result["format_exit_code"] = format_code

    format_issues = []
    if format_code not in NON_ISSUE_EXIT_CODES and format_code != -1:
        # ruff format --check 返回 1 表示格式有问题
        # 解析 diff 输出
        format_issues = parse_format_diff(format_stdout)
    result["format_issues"] = format_issues

    # 4. 汇总统计
    all_issues = lint_issues + format_issues
    severity_counter: Counter = Counter()
    for issue in all_issues:
        severity_counter[issue["severity"]] += 1

    affected_files = set()
    for issue in all_issues:
        if issue.get("file"):
            affected_files.add(issue["file"])

    result["files_with_issues"] = len(affected_files)
    result["total_issues"] = len(all_issues)
    result["severity_distribution"] = dict(severity_counter)

    # fix 模式下统计修复数（lint 修复通过 stderr 提示）
    if fix_mode:
        fix_matches = re.findall(r"Fixed (\d+) issue", lint_stdout + lint_stderr)
        if fix_matches:
            result["fixed_count"] = sum(int(m) for m in fix_matches)
        else:
            result["fixed_count"] = 0

    return result


def parse_format_diff(diff_output: str) -> list[dict]:
    """解析 ruff format --diff 的输出，提取格式问题。"""
    issues = []
    # ruff format --diff 输出 git-like diff
    # 每个有问题的文件会出现在 diff 中
    current_file = None
    for line in diff_output.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            # 提取文件名
            parts = line.split()
            if len(parts) >= 2:
                # 去除 a/ b/ 前缀
                fname = parts[-1]
                if fname.endswith(".py"):
                    current_file = fname

    if current_file and diff_output.strip():
        issues.append({
            "file": current_file,
            "line": 0,
            "column": 0,
            "code": "FMT001",
            "message": "文件格式与 ruff format 不匹配",
            "rule": "format",
            "severity": "info",
            "source": "ruff format --check",
        })

    return issues


def print_report(result: dict) -> None:
    """打印人类可读的检查报告。"""
    print("=" * 70)
    print("  J.A.R.V.I.S. — ruff 代码质量检查报告")
    print("=" * 70)

    # ruff 状态
    if not result.get("ruff_available"):
        print("\n  [×] ruff 未安装")
        print("\n  请运行以下命令安装:")
        print("      pip install ruff")
        print("      或")
        print("      uv tool install ruff")
        print("\n  安装后重新运行本脚本即可。")
        print("=" * 70)
        return

    print(f"\n  [✓] ruff {result.get('ruff_version', 'unknown')}")
    print(f"  模式: {'自动修复 (--fix)' if result.get('mode') == 'fix' else '检查模式'}")
    print(f"  扫描目录: {result.get('src_directory', 'N/A')}")

    # Lint 结果
    lint_code = result.get("lint_exit_code")
    if lint_code == -1:
        print("\n  [×] ruff check 执行失败")
        print(f"      错误: {result.get('lint_error', '未知错误')}")
    elif lint_code == 0:
        print("\n  [✓] ruff check: 通过（无 lint 问题）")
    elif lint_code == 1:
        print(f"\n  [!] ruff check: 发现 {len(result.get('lint_issues', []))} 个 lint 问题")
    elif lint_code in (2, 123):
        print(f"\n  [!] ruff check: 内部错误 (exit {lint_code})")
        if result.get("lint_error"):
            print(f"      错误: {result['lint_error']}")

    # Format 结果
    format_code = result.get("format_exit_code")
    if format_code == -1:
        print("\n  [×] ruff format 执行失败")
    elif format_code == 0:
        print("\n  [✓] ruff format: 通过（格式匹配）")
    elif format_code == 1:
        print(f"\n  [!] ruff format: {len(result.get('format_issues', []))} 个文件格式不匹配")

    # 严重级别分布
    severity_dist = result.get("severity_distribution", {})
    if severity_dist:
        print("\n  --- 严重级别分布 ---")
        for level in ("error", "warning", "info", "unknown"):
            count = severity_dist.get(level, 0)
            if count > 0:
                icon = {"error": "[!!]", "warning": "[! ]", "info": "[i]", "unknown": "[?]"}.get(level, "[ ]")
                print(f"    {icon} {level.upper():>8}: {count}")

    # 汇总
    files = result.get("files_with_issues", 0)
    total = result.get("total_issues", 0)
    print("\n  --- 汇总 ---")
    print(f"    问题文件数: {files}")
    print(f"    问题总数:   {total}")

    if result.get("mode") == "fix" and result.get("fixed_count", 0) > 0:
        print(f"    自动修复数: {result['fixed_count']}")

    # 详细问题列表
    all_issues = result.get("lint_issues", []) + result.get("format_issues", [])
    if all_issues:
        print("\n  --- 问题明细（前 20 条） ---")
        for i, issue in enumerate(all_issues[:20]):
            code = issue.get("code", "???")
            sev = issue.get("severity", "unknown")[:1].upper()
            fname = issue.get("file", "unknown")
            line = issue.get("line", 0)
            msg = issue.get("message", "")[:80]
            location = f"{fname}:{line}" if line else fname
            print(f"    {i+1:2}. [{sev}] {code} @ {location}")
            print(f"        {msg}")

        if len(all_issues) > 20:
            print(f"    ... 还有 {len(all_issues) - 20} 条问题未显示")

    print("=" * 70)


def write_json_report(result: dict) -> None:
    """将结果写入 JSON 报告文件。"""
    report_path = REPORT_FILE
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  详细报告已保存至: {report_path}")
    except (OSError, TypeError) as e:
        print(f"\n  [!] 无法写入报告文件: {e}")


def get_exit_code(result: dict) -> int:
    """根据检查结果决定退出码。"""
    if not result.get("ruff_available"):
        return 2  # ruff 未安装

    # 有 lint 问题
    if result.get("lint_exit_code") == 1:
        return 1

    # 有 format 问题
    if result.get("format_exit_code") == 1:
        return 1

    # 执行错误
    if result.get("lint_exit_code") == -1:
        return 2

    return 0  # 全部通过


def main():
    parser = argparse.ArgumentParser(
        description="小奕 J.A.R.V.I.S. — ruff 代码质量检查工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/ruff_check.py                    # 检查模式
  python scripts/ruff_check.py --fix              # 自动修复
  python scripts/ruff_check.py --src src/core     # 指定目录
  python scripts/ruff_check.py --json             # JSON 输出
        """,
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="自动修复可修复的问题（ruff check --fix）",
    )
    parser.add_argument(
        "--src",
        type=str,
        default=str(SRC_DIR),
        help=f"指定扫描目录（默认: {SRC_DIR}）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="仅输出 JSON 格式结果",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="生成 JSON 报告文件",
    )

    args = parser.parse_args()
    src_dir = Path(args.src)

    result = run_checks(src_dir, fix_mode=args.fix)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print_report(result)

    if args.report:
        write_json_report(result)

    sys.exit(get_exit_code(result))


if __name__ == "__main__":
    main()
