"""Run the required local integration profile against repository-owned services."""

from __future__ import annotations

import argparse
import os
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = "service did not respond"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_integration(*, timeout: int = 30, require_services: bool = True) -> int:
    """Start Core, Ollama fixture, and Express, then run the profile."""
    if not require_services:
        raise ValueError("The CI runner only supports required-services mode")

    core_port = _free_port()
    ollama_port = _free_port()
    express_port = _free_port()
    processes: list[subprocess.Popen] = []

    with tempfile.TemporaryDirectory(prefix="jarvis-ci-integration-") as temp_dir:
        temp_path = Path(temp_dir)
        def start(command, *, cwd, env, name):
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            processes.append(process)
            return process

        base_env = os.environ.copy()
        base_env["PYTHONUNBUFFERED"] = "1"

        try:
            fixture = start(
                [sys.executable, str(FIXTURE), "--port", str(ollama_port)],
                cwd=ROOT,
                env=base_env,
                name="ollama-fixture",
            )
            _wait_for_health(f"http://127.0.0.1:{ollama_port}/api/version", timeout)

            core_env = {
                **base_env,
                "JARVIS_HOST": "127.0.0.1",
                "OLLAMA_BASE_URL": f"http://127.0.0.1:{ollama_port}",
            }
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
            _wait_for_health(f"http://127.0.0.1:{core_port}/api/health", timeout)

            express_env = {
                **base_env,
                "HOST": "127.0.0.1",
                "PORT": str(express_port),
                "JARVIS_HOST": "127.0.0.1",
                "JARVIS_CORE_API_URL": f"http://127.0.0.1:{core_port}",
                "OLLAMA_HOST": "127.0.0.1",
                "OLLAMA_PORT": str(ollama_port),
            }
            express = start(
                ["node", "server.js"],
                cwd=ROOT / "frontend",
                env=express_env,
                name="express",
            )
            _wait_for_health(f"http://127.0.0.1:{express_port}/api/health", timeout)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROFILE),
                    "--express-url",
                    f"http://127.0.0.1:{express_port}",
                    "--model",
                    "fixture",
                    "--timeout",
                    str(timeout),
                    "--require-services",
                ],
                cwd=ROOT,
                env=express_env,
                check=False,
            )
            return result.returncode
        finally:
            for process in reversed(processes):
                _stop(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--require-services", action="store_true", default=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_integration(timeout=args.timeout, require_services=args.require_services)
    except Exception as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
