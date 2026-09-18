#!/usr/bin/env python3
"""discover_tests.py — 为完整 unittest discovery 提供有界超时与精确挂起归因

tests/run_all.py 自带 --timeout，但 "python -m unittest discover" 没有等价开关：
一个卡死的用例只能等 CI 作业级上限把整个作业杀掉，日志被截断，也无法知道究竟是
哪个用例挂起。本脚本把 discovery 放进受控子进程：

1. 强制 verbose 输出，按块镜像到本进程的 stdout/stderr，不做整体缓冲；
2. 跟踪 "已开始但尚未给出结果" 的用例，超时时报出该用例 ID 与最近若干条结果；
   同时解析 unittest 自身的 "Ran N tests" 摘要作为权威计数——逐条归因是尽力而为
   的（用例向 stderr 写入换行会打断计数行），摘要计数不会；
3. 超时或溢出后终止整棵进程树（POSIX 进程组 / Windows taskkill /T），避免 Worker
   测试留下的孙进程继续持有管道；
4. 每条流保留独立原始字节预算，溢出即终止子进程并失败关闭；
5. 可选 --json-report 写出与 run_all.py 同构的机器可读摘要。

本脚本是运行测试的外层门禁，因此只依赖标准库，不导入被测源码。

使用方式：
    python scripts/discover_tests.py --timeout 1800
    python scripts/discover_tests.py --timeout 1800 --json-report discover-report.json
"""

import argparse
import codecs
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_MAX_STREAM_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_RECENT_TEST_LIMIT = 20
_KILL_GRACE_SECONDS = 5.0
_JOIN_GRACE_SECONDS = 2.0
_POLL_INTERVAL_SECONDS = 0.05

# unittest verbose 逐用例先写 "<描述> ... "，得到结果后再补 "ok"/"FAIL"/... 。
# 因此一条只有前半段的未完成行，正是当前在跑的用例。
_STARTED_PATTERN = re.compile(r"^(?P<description>.+?) \.\.\. $")
_FINISHED_PATTERN = re.compile(
    r"^(?P<description>.+?) \.\.\. "
    r"(?P<outcome>ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)$"
)
# str(test) 形如 "test_foo (pkg.mod.TestCase.test_foo)"，可带 subtest 后缀。
_TEST_ID_PATTERN = re.compile(r"^\S+ \(\S+\)( \[.*\])?$")
# unittest 结尾摘要。位数上界避免超长数字串触发 int 转换限制。
_RAN_PATTERN = re.compile(r"^Ran (\d{1,9}) tests? in ")
_OUTCOME_PATTERN = re.compile(r"^(?:OK|FAILED)(?: \(.*\))?$")


def _write_report(json_report: str, payload: dict) -> None:
    if not json_report:
        return
    Path(json_report).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class _DiscoveryProgress:
    """跟踪 verbose 输出中已开始未结束的用例，用于超时归因。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending = ""
        self._previous_line = ""
        self._in_flight = ""
        self._completed = 0
        self._ran_tests = None
        self._outcome = ""
        self._recent: deque = deque(maxlen=_RECENT_TEST_LIMIT)

    def feed(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._pending += text
            while True:
                index = self._pending.find("\n")
                if index < 0:
                    break
                line = self._pending[:index].rstrip("\r")
                self._pending = self._pending[index + 1 :]
                self._consume_line(line)
            self._observe_pending()

    def _consume_line(self, line: str) -> None:
        match = _FINISHED_PATTERN.match(line)
        if match:
            description = self._resolve(match.group("description"))
            self._completed += 1
            self._recent.append(f"{description} ... {match.group('outcome')}")
            self._in_flight = ""
        else:
            self._consume_summary_line(line)
        self._previous_line = line

    def _consume_summary_line(self, line: str) -> None:
        # 嵌套 runner（smoke 覆盖测试）也会把自己的摘要写进同一条流，因此外层
        # 运行的摘要是"最后一次"观察到的，而不是第一次。
        ran_match = _RAN_PATTERN.match(line)
        if ran_match:
            self._ran_tests = int(ran_match.group(1))
            return
        if _OUTCOME_PATTERN.match(line):
            self._outcome = line.strip()

    def _observe_pending(self) -> None:
        match = _STARTED_PATTERN.match(self._pending)
        if match:
            self._in_flight = self._resolve(match.group("description"))

    def _resolve(self, description: str) -> str:
        # 带 docstring 的用例会把 str(test) 与首行文档分成两行输出，此时用例 ID
        # 位于上一整行，需要拼回去才能定位。
        description = description.strip()
        if _TEST_ID_PATTERN.match(description):
            return description
        previous = self._previous_line.strip()
        if _TEST_ID_PATTERN.match(previous):
            return f"{previous} :: {description}"
        return description

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "completed": self._completed,
                "ran_tests": self._ran_tests,
                "outcome": self._outcome,
                "in_flight": self._in_flight,
                "recent": list(self._recent),
            }


def _write_through(buffer: object, sink: object, data: bytes) -> None:
    try:
        if buffer is not None:
            buffer.write(data)
            buffer.flush()
        else:
            sink.write(data.decode("utf-8", errors="replace"))
            sink.flush()
    except (OSError, ValueError, AttributeError):
        return


def _mirror_stream(
    stream: object,
    sink: object,
    limit: int,
    overflow: threading.Event,
    progress: object,
) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buffer = getattr(sink, "buffer", None)
    total = 0
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            elif not isinstance(chunk, bytes):
                chunk = bytes(chunk)
            if total >= limit:
                # 预算已耗尽：继续排空管道，避免子进程在被终止前阻塞于写入。
                overflow.set()
                continue
            retained = chunk[: limit - total]
            total += len(retained)
            if len(retained) < len(chunk):
                overflow.set()
            _write_through(buffer, sink, retained)
            if progress is not None:
                progress.feed(decoder.decode(retained))
    except (OSError, ValueError, TypeError):
        return
    finally:
        if progress is not None:
            try:
                progress.feed(decoder.decode(b"", True))
            except (UnicodeDecodeError, ValueError):
                return


def _terminate_process_tree(process: object) -> None:
    """尽力终止子进程及其后代，避免测试派生的孙进程继续运行。"""
    pid = getattr(process, "pid", None)
    if pid is not None:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=_KILL_GRACE_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        else:
            try:
                group = os.getpgid(pid)
                own_group = os.getpgid(0)
            except (OSError, AttributeError):
                group = None
                own_group = None
            # 只有子进程自成进程组时才整组终止，避免误杀本进程所在的组。
            if group is not None and group != own_group:
                try:
                    os.killpg(group, signal.SIGKILL)
                except (OSError, AttributeError):
                    pass
    try:
        process.kill()
    except (OSError, AttributeError, ValueError):
        pass


def discovery_command(start_directory: str, pattern: str) -> list:
    return [
        sys.executable,
        "-u",
        "-m",
        "unittest",
        "discover",
        "-v",
        "-s",
        start_directory,
        "-p",
        pattern,
    ]


def discovery_title(start_directory: str, pattern: str) -> str:
    return (
        f"J.A.R.V.I.S. unittest discovery - {start_directory} ({pattern})"
    )


def run_discovery(
    timeout: int = 0,
    json_report: str = "",
    start_directory: str = "tests",
    pattern: str = "test_*.py",
    stream_limit: int = _MAX_STREAM_BYTES,
) -> int:
    title = discovery_title(start_directory, pattern)
    print("=" * 60)
    print(title)
    print("=" * 60)
    sys.stdout.flush()

    progress = _DiscoveryProgress()
    overflow = threading.Event()
    started = time.monotonic()

    popen_kwargs = {
        "cwd": str(PROJECT_ROOT),
        "shell": False,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name != "nt":
        # 自成进程组，超时后可以整组回收孙进程。
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            discovery_command(start_directory, pattern), **popen_kwargs
        )
    except (OSError, ValueError) as error:
        print(f"discovery 启动失败: {error}", file=sys.stderr)
        _write_report(
            json_report,
            {
                "title": title,
                "start_directory": start_directory,
                "pattern": pattern,
                "ran_tests": None,
                "outcome": "",
                "tests_reported": 0,
                "in_flight_test": "",
                "recent_tests": [],
                "elapsed_seconds": 0.0,
                "returncode": None,
                "success": False,
                "timeout_seconds": timeout,
                "timeout_expired": False,
                "output_limited": False,
            },
        )
        return 1

    readers = [
        threading.Thread(
            target=_mirror_stream,
            args=(process.stdout, sys.stdout, stream_limit, overflow, None),
            daemon=True,
        ),
        threading.Thread(
            target=_mirror_stream,
            args=(process.stderr, sys.stderr, stream_limit, overflow, progress),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    deadline = started + timeout if timeout > 0 else None
    timed_out = False
    while True:
        if overflow.is_set():
            break
        if process.poll() is not None:
            break
        if deadline is not None and time.monotonic() >= deadline:
            timed_out = True
            break
        try:
            process.wait(timeout=_POLL_INTERVAL_SECONDS)
        except subprocess.TimeoutExpired:
            continue
        except (OSError, ValueError):
            break

    if timed_out or overflow.is_set():
        _terminate_process_tree(process)
        try:
            process.wait(timeout=_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass

    for reader in readers:
        reader.join(timeout=_JOIN_GRACE_SECONDS)
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except (OSError, AttributeError, ValueError):
            pass

    elapsed = time.monotonic() - started
    state = progress.snapshot()
    output_limited = overflow.is_set()
    returncode = process.returncode
    success = returncode == 0 and not timed_out and not output_limited

    print()
    print("=" * 60)
    print(
        f"Discovery: {state['ran_tests']} tests ran "
        f"({state['completed']} outcomes attributed), "
        f"{elapsed:.1f}s elapsed, exit {returncode}"
    )
    if state["outcome"]:
        print(f"Summary: {state['outcome']}")
    if timed_out:
        print(f"Timeout: {timeout}s exceeded")
        if state["in_flight"]:
            print(f"Hung test: {state['in_flight']}")
        else:
            print("Hung test: unknown (no test in flight at the deadline)")
        for line in state["recent"]:
            print(f"  last: {line}")
    if output_limited:
        print(f"Output exceeds {stream_limit} bytes on a single stream")
    print("=" * 60)
    sys.stdout.flush()

    _write_report(
        json_report,
        {
            "title": title,
            "start_directory": start_directory,
            "pattern": pattern,
            "ran_tests": state["ran_tests"],
            "outcome": state["outcome"],
            "tests_reported": state["completed"],
            "in_flight_test": state["in_flight"],
            "recent_tests": state["recent"],
            "elapsed_seconds": round(elapsed, 3),
            "returncode": returncode,
            "success": success,
            "timeout_seconds": timeout,
            "timeout_expired": timed_out,
            "output_limited": output_limited,
        },
    )
    return 0 if success else 1


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
        prog="discover_tests.py",
        description=(
            "Run the full unittest discovery under a cooperative deadline and "
            "report which test was in flight if the deadline expires."
        ),
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
        help="write the discovery summary to PATH as JSON",
    )
    parser.add_argument(
        "--start-directory",
        default="tests",
        metavar="DIR",
        help="discovery start directory (default: tests)",
    )
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        metavar="GLOB",
        help="test file pattern (default: test_*.py)",
    )
    return parser


def main(argv=None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    return run_discovery(
        timeout=arguments.timeout,
        json_report=arguments.json_report,
        start_directory=arguments.start_directory,
        pattern=arguments.pattern,
    )


if __name__ == "__main__":
    sys.exit(main())
