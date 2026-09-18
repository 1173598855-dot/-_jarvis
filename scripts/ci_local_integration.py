"""Run the required local integration profile against repository-owned services.

每个阶段都在一个共同的整体截止时间内运行：三次健康等待和 profile 子进程各自取
"本阶段预算"与"整体剩余时间"的较小值。此前 profile 的 subprocess.run() 没有
timeout，`--timeout 3` 也能让一个卡死的 profile 跑满 60 秒，只有 CI 作业级上限兜底。

服务进程的输出写入受管临时目录；任何阶段失败时打印有界日志尾部，便于定位。
超时与退出路径都回收整棵进程树，避免服务的孙进程继续占用端口。
"""

from __future__ import annotations

import argparse
import locale
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "scripts" / "local_integration_profile.py"
FIXTURE = ROOT / "scripts" / "local_ollama_fixture.py"

_DEFAULT_OVERALL_TIMEOUT = 300
_HEALTH_POLL_SECONDS = 0.1
_STOP_GRACE_SECONDS = 5.0
_KILL_GRACE_SECONDS = 5.0
_LOG_TAIL_BYTES = 4096
_CLEANUP_ATTEMPTS = 20
_CLEANUP_RETRY_SECONDS = 0.1


class IntegrationTimeout(RuntimeError):
    """Raised when the overall deadline is exhausted before the run finishes."""


class _Service:
    """A long-lived child process plus the log file collecting its output."""

    def __init__(self, name: str, process: subprocess.Popen, log_path: Path) -> None:
        self.name = name
        self.process = process
        self.log_path = log_path


class _PortReservation:
    """A loopback port held bound until the child that needs it is started.

    The previous helper bound a port, closed the socket and returned the
    number, so nothing owned the port between allocation and the moment the
    service bound it. That window spans two other allocations plus the earlier
    services' startup and health waits, and any other process on the host can
    take the port inside it. Keeping the reserving socket bound closes the
    window down to the release-then-exec handoff and makes the three ports
    distinct by construction.
    """

    def __init__(self, sock: socket.socket) -> None:
        self._socket: socket.socket | None = sock
        self.port = int(sock.getsockname()[1])

    def release(self) -> None:
        """Drop the reservation so the child can bind. Safe to call twice."""
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()


def _reserve_port() -> _PortReservation:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # On Windows a plain bind can still be taken by a SO_REUSEADDR socket,
        # so ask for exclusive ownership where the option exists. SO_REUSEADDR
        # is deliberately not set: the reservation must not be shareable.
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        sock.bind(("127.0.0.1", 0))
        # Listening makes the reservation exclusive on POSIX too, where an
        # unconnected bound socket alone does not always refuse a reusing bind.
        sock.listen(1)
    except OSError:
        sock.close()
        raise
    return _PortReservation(sock)


def _reserve_ports(count: int) -> list:
    """Hold `count` distinct loopback ports at once, or release them all."""
    reservations: list = []
    try:
        for _ in range(count):
            reservations.append(_reserve_port())
        ports = {reservation.port for reservation in reservations}
        if len(ports) != count:
            raise RuntimeError(
                f"expected {count} distinct loopback ports, got {sorted(ports)}"
            )
    except (OSError, RuntimeError):
        for reservation in reservations:
            reservation.release()
        raise
    return reservations


def _remaining(deadline: float | None, stage: str) -> float | None:
    """Time left before the overall deadline, or None when unbounded."""
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise IntegrationTimeout(f"overall timeout exhausted before {stage}")
    return remaining


def _stage_budget(deadline: float | None, stage: str, budget: float) -> float:
    remaining = _remaining(deadline, stage)
    if remaining is None:
        return budget
    return min(budget, remaining)


def _decode_service_output(data: bytes) -> str:
    """Decode child output, tolerating a non-UTF-8 console encoding.

    Windows services here emit text in the active code page (GBK on this
    host), so a hardcoded UTF-8 decode turned the very error the tail exists
    to show into replacement characters. UTF-8 is self-validating, so a strict
    decode that succeeds is authoritative; only on failure is the locale
    encoding tried, with a lossy UTF-8 decode as the final fallback.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        fallback = locale.getpreferredencoding(False)
    except (AttributeError, ValueError):
        fallback = ""
    if fallback and fallback.lower().replace("-", "") not in {"utf8"}:
        try:
            return data.decode(fallback)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def _read_log_tail(log_path: Path | None) -> str:
    if log_path is None:
        return ""
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _LOG_TAIL_BYTES))
            data = handle.read(_LOG_TAIL_BYTES)
    except OSError:
        return ""
    return _decode_service_output(data).strip()


def _remove_log_dir(log_dir: Path) -> None:
    """Discard the log directory without letting cleanup fail the run.

    On Windows a stopped service's log handle can stay open briefly after the
    process exits, so `TemporaryDirectory` raised `WinError 32` and turned an
    already-passing profile into exit 2. Retry for a bounded moment, then report
    the leftover path instead of overwriting the real result.
    """
    last_error: OSError | None = None
    for attempt in range(_CLEANUP_ATTEMPTS):
        try:
            shutil.rmtree(log_dir)
            return
        except FileNotFoundError:
            return
        except OSError as error:
            last_error = error
            if attempt + 1 < _CLEANUP_ATTEMPTS:
                time.sleep(_CLEANUP_RETRY_SECONDS)
    print(
        f"WARNING: could not remove service log directory {log_dir}: {last_error}",
        file=sys.stderr,
    )


def _wait_for_health(
    url: str,
    timeout: float,
    process: subprocess.Popen | None = None,
    name: str = "",
) -> None:
    """Poll until the service answers, or fail as soon as it is known dead."""
    deadline = time.monotonic() + timeout
    last_error = "service did not respond"
    label = name or url
    while time.monotonic() < deadline:
        # A service that already exited can never become healthy, so waiting out
        # the remaining budget only hides the real failure.
        if process is not None:
            returncode = process.poll()
            if returncode is not None:
                raise RuntimeError(
                    f"{label} exited with code {returncode} before becoming healthy"
                )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(_HEALTH_POLL_SECONDS)
    raise RuntimeError(f"Timed out waiting for {label} at {url}: {last_error}")


def _terminate_tree(process: subprocess.Popen | None) -> None:
    """Best-effort reclamation of a child and any descendants it left behind."""
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
            # Only signal a group the child owns, never the harness's own group.
            if group is not None and group != own_group:
                try:
                    os.killpg(group, signal.SIGKILL)
                except (OSError, AttributeError):
                    pass
    try:
        process.kill()
    except (OSError, AttributeError, ValueError):
        pass


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except (OSError, AttributeError, ValueError):
        pass
    try:
        process.wait(timeout=_STOP_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    except (OSError, ValueError):
        return
    _terminate_tree(process)
    try:
        process.wait(timeout=_KILL_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass


def _report_service_logs(services: list) -> None:
    for service in services:
        tail = _read_log_tail(service.log_path)
        if tail:
            print(f"--- {service.name} output (tail) ---", file=sys.stderr)
            print(tail, file=sys.stderr)


def run_integration(
    *,
    timeout: int = 30,
    require_services: bool = True,
    overall_timeout: int = _DEFAULT_OVERALL_TIMEOUT,
) -> int:
    """Start Core, Ollama fixture, and Express, then run the profile."""
    if not require_services:
        raise ValueError("The CI runner only supports required-services mode")

    reservations = _reserve_ports(3)
    core_reservation, ollama_reservation, express_reservation = reservations
    core_port = core_reservation.port
    ollama_port = ollama_reservation.port
    express_port = express_reservation.port
    services: list = []
    deadline = time.monotonic() + overall_timeout if overall_timeout > 0 else None

    log_dir = Path(tempfile.mkdtemp(prefix="jarvis-ci-integration-"))
    try:
        handles: list = []

        def start(command, *, cwd, env, name):
            log_path = log_dir / f"{name}.log"
            handle = log_path.open("wb")
            handles.append(handle)
            popen_kwargs = {
                "cwd": str(cwd),
                "env": env,
                "stdout": handle,
                "stderr": subprocess.STDOUT,
            }
            if os.name != "nt":
                # Own session so a wedged service's descendants stay reclaimable.
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(command, **popen_kwargs)
            services.append(_Service(name, process, log_path))
            return process

        base_env = os.environ.copy()
        base_env["PYTHONUNBUFFERED"] = "1"
        # Make Python children emit UTF-8 regardless of the host code page so
        # their captured tracebacks stay readable in CI logs.
        base_env["PYTHONIOENCODING"] = "utf-8"

        try:
            ollama_reservation.release()
            fixture = start(
                [sys.executable, str(FIXTURE), "--port", str(ollama_port)],
                cwd=ROOT,
                env=base_env,
                name="ollama-fixture",
            )
            _wait_for_health(
                f"http://127.0.0.1:{ollama_port}/api/version",
                _stage_budget(deadline, "ollama-fixture health", timeout),
                fixture,
                "ollama-fixture",
            )

            core_env = {
                **base_env,
                "JARVIS_HOST": "127.0.0.1",
                "OLLAMA_BASE_URL": f"http://127.0.0.1:{ollama_port}",
            }
            core_reservation.release()
            core = start(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "src.main_fastapi:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(core_port),
                ],
                cwd=ROOT,
                env=core_env,
                name="core",
            )
            _wait_for_health(
                f"http://127.0.0.1:{core_port}/api/health",
                _stage_budget(deadline, "core health", timeout),
                core,
                "core",
            )

            express_env = {
                **base_env,
                "HOST": "127.0.0.1",
                "PORT": str(express_port),
                "JARVIS_HOST": "127.0.0.1",
                "JARVIS_CORE_API_URL": f"http://127.0.0.1:{core_port}",
                "OLLAMA_HOST": "127.0.0.1",
                "OLLAMA_PORT": str(ollama_port),
            }
            express_reservation.release()
            express = start(
                ["node", "server.js"],
                cwd=ROOT / "frontend",
                env=express_env,
                name="express",
            )
            _wait_for_health(
                f"http://127.0.0.1:{express_port}/api/health",
                _stage_budget(deadline, "express health", timeout),
                express,
                "express",
            )

            return _run_profile(
                express_url=f"http://127.0.0.1:{express_port}",
                timeout=timeout,
                env=express_env,
                budget=_stage_budget(deadline, "profile", float(timeout)),
                services=services,
            )
        except (RuntimeError, OSError) as error:
            print(f"FAILED: {error}", file=sys.stderr)
            _report_service_logs(services)
            return 2
        finally:
            # Reservations released above are already closed; this only covers
            # the ports whose service never started.
            for reservation in reservations:
                reservation.release()
            for service in reversed(services):
                _stop(service.process)
            for handle in handles:
                try:
                    handle.close()
                except OSError:
                    pass
    finally:
        _remove_log_dir(log_dir)


def _run_profile(
    *,
    express_url: str,
    timeout: int,
    env: dict,
    budget: float,
    services: list,
) -> int:
    """Run the profile under its own deadline instead of waiting indefinitely."""
    command = [
        sys.executable,
        str(PROFILE),
        "--express-url",
        express_url,
        "--model",
        "fixture",
        "--timeout",
        str(timeout),
        "--require-services",
    ]
    process = subprocess.Popen(command, cwd=str(ROOT), env=env)
    try:
        return process.wait(timeout=budget)
    except subprocess.TimeoutExpired:
        _terminate_tree(process)
        try:
            process.wait(timeout=_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        print(
            f"FAILED: integration profile exceeded {budget:g}s",
            file=sys.stderr,
        )
        _report_service_logs(services)
        return 2


def _positive_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be an integer") from None
    if seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=_positive_seconds, default=30)
    parser.add_argument(
        "--overall-timeout",
        type=_positive_seconds,
        default=_DEFAULT_OVERALL_TIMEOUT,
        metavar="SECONDS",
        help="bound the whole run, including service startup and the profile",
    )
    parser.add_argument("--require-services", action="store_true", default=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_integration(
            timeout=args.timeout,
            require_services=args.require_services,
            overall_timeout=args.overall_timeout,
        )
    except Exception as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
