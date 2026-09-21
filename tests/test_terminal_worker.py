"""Regression tests for the process-isolated terminal worker."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.kernel.process_containment import (
    ProcessContainmentError,
    process_group_popen_kwargs,
)
from core.kernel.terminal_executor import (
    CommandRisk,
    TerminalCommand,
    TerminalExecutor,
)
from core.kernel.terminal_worker import (
    WORKER_REQUEST_LIMIT,
    WORKER_RESPONSE_LIMIT,
    TerminalWorker,
    _worker_main,
    _worker_sandbox_path,
)
from core.kernel.worker_filesystem_isolation import WorkerFilesystemIsolationError
from core.kernel.worker_network_isolation import WorkerNetworkIsolationError
from core.kernel.worker_resource_limits import WorkerResourceLimitError
from core.kernel.worker_windows_container import WorkerContainerError

_WORKER_TIMESTAMP = "2026-08-17T12:34:56+00:00"


def _worker_payload(**overrides: object) -> str:
    response = {
        "command_id": "wire",
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "duration": 0.1,
        "success": True,
        "risk_level": "safe",
        "timestamp": _WORKER_TIMESTAMP,
    }
    response.update(overrides)
    return json.dumps(response)


class _PendingWorkerProcess:
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
        return self.stdout.getvalue().decode("utf-8"), self.stderr.getvalue().decode("utf-8")


class _IsolatedWorkerProcess(_PendingWorkerProcess):
    def __init__(self, stdout: bytes, order: list[str]) -> None:
        super().__init__(stdout)
        self.pid = 4242
        self.order = order
        self.close_spawn_handle_calls = 0

    def resume(self) -> None:
        self.order.append("resume")

    def close_spawn_handle(self) -> None:
        self.close_spawn_handle_calls += 1


class _FakeTerminalSandbox:
    def __init__(
        self,
        order: list[str],
        *,
        fail_stage: Exception | None = None,
        spawn_error: Exception | None = None,
        close_errors: list[Exception | None] | None = None,
    ):
        self.order = order
        self.fail_stage = fail_stage
        self.spawn_error = spawn_error
        self.root = Path(tempfile.mkdtemp(prefix=".test-terminal-os-root-"))
        self.code_root = self.root / "code"
        self.writable_root = self.root / "tmp"
        self.code_root.mkdir()
        self.writable_root.mkdir()
        self.interpreter = PureWindowsPath("C:/Python/python.exe")
        self.stages: list[tuple[Path, str]] = []
        self.spawn_calls: list[dict[str, object]] = []
        self.processes: list[_IsolatedWorkerProcess] = []
        self.close_errors = list(close_errors or [])
        self.closed = False

    def stage(self, source: Path, name: str) -> Path:
        self.order.append(f"stage:{name}")
        if self.fail_stage is not None:
            raise self.fail_stage
        destination = self.code_root / name
        destination.mkdir()
        self.stages.append((source, name))
        return destination

    def spawn(self, arguments, *, cwd, environment, **keywords):
        self.order.append("spawn")
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawn_calls.append({
            "arguments": list(arguments),
            "cwd": cwd,
            "environment": dict(environment),
            "keywords": dict(keywords),
        })
        process = _IsolatedWorkerProcess(
            _worker_payload(command_id="isolated").encode("utf-8"), self.order
        )
        self.processes.append(process)
        return process

    def close(self) -> None:
        self.order.append("sandbox-close")
        if self.close_errors:
            error = self.close_errors.pop(0)
            if error is not None:
                raise error
        self.closed = True
        shutil.rmtree(self.root, ignore_errors=True)

    def close_spawn_handle(self) -> None:
        return None


class _RecordingContainment:
    def __init__(self) -> None:
        self.terminated = False
        self.waited = False
        self.closed = False

    def terminate(self, *, force: bool) -> bool:
        self.terminated = True
        return True

    def wait_empty(self, _timeout: float) -> bool:
        self.waited = True
        return True

    def close(self) -> bool:
        self.closed = True
        return True

def _load_http_main():
    import importlib.util

    path = Path(__file__).parent.parent / "src" / "main.py"
    spec = importlib.util.spec_from_file_location("terminal_worker_http_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTerminalWorker(unittest.TestCase):
    def setUp(self):
        self._worker_tmpdir_patch = patch.dict(
            os.environ,
            {"TMPDIR": tempfile.gettempdir()},
            clear=False,
        )
        self._worker_tmpdir_patch.start()

    def tearDown(self):
        self._worker_tmpdir_patch.stop()

    def test_explicit_os_isolation_false_overrides_injected_platform_factory(self):
        worker = TerminalWorker(
            os_isolation=False,
            macos_sandbox_factory=lambda: self.fail("factory must not be used"),
        )
        try:
            self.assertFalse(worker._should_use_os_isolation())
        finally:
            worker.close()

    def test_injected_macos_factory_enables_isolation_for_a_non_macos_test_host(self):
        def factory():
            return _FakeTerminalSandbox([])

        worker = TerminalWorker(macos_sandbox_factory=factory)
        try:
            self.assertTrue(worker._should_use_os_isolation())
        finally:
            worker.close()

    def test_macos_isolated_launch_stages_once_and_uses_the_sandbox_root(self):
        order: list[str] = []
        sandbox = _FakeTerminalSandbox(order)
        worker = TerminalWorker(
            os_isolation=True,
            macos_sandbox_factory=lambda: sandbox,
        )

        def attach(_process):
            order.append("attach")
            return _RecordingContainment()

        try:
            with patch("core.kernel.terminal_worker.os.name", "posix"), patch(
                "core.kernel.terminal_worker.sys.platform", "darwin"
            ), patch(
                "core.kernel.terminal_worker.ProcessTreeContainment.attach",
                side_effect=attach,
            ), patch(
                "core.kernel.terminal_worker._bounded_process_communicate",
                return_value=(
                    _worker_payload(command_id="isolated").encode("utf-8"),
                    b"",
                    False,
                    False,
                ),
            ):
                first = worker.execute(
                    TerminalCommand(
                        id="isolated",
                        command="echo",
                        args=["one"],
                        risk_level=CommandRisk.SAFE,
                    )
                )
                second = worker.execute(
                    TerminalCommand(
                        id="isolated",
                        command="echo",
                        args=["two"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertTrue(first.success)
            self.assertTrue(second.success)
            self.assertEqual([name for _, name in sandbox.stages], ["src"])
            self.assertEqual(len(sandbox.spawn_calls), 2)
            launch = sandbox.spawn_calls[0]
            self.assertEqual(
                launch["arguments"][1:],
                ["-S", "-u", "-m", "core.kernel.terminal_worker", "--worker"],
            )
            self.assertEqual(
                str(launch["cwd"]).replace("\\", "/").casefold(),
                str(sandbox.code_root / "src").replace("\\", "/").casefold(),
            )
            self.assertEqual(
                launch["environment"]["TMPDIR"], str(sandbox.writable_root)
            )
        finally:
            worker.close()

        self.assertTrue(sandbox.closed)
        self.assertEqual(order[:4], ["stage:src", "spawn", "attach", "spawn"])

    def test_windows_isolated_launch_attaches_before_resume(self):
        order: list[str] = []
        sandbox = _FakeTerminalSandbox(order)
        worker = TerminalWorker(
            os_isolation=True,
            container_factory=lambda: sandbox,
        )

        def attach(_process):
            order.append("attach")
            return _RecordingContainment()

        try:
            with patch("core.kernel.terminal_worker.os.name", "nt"), patch(
                "core.kernel.terminal_worker.sys.platform", "win32"
            ), patch(
                "core.kernel.terminal_worker.ProcessTreeContainment.attach",
                side_effect=attach,
            ), patch(
                "core.kernel.terminal_worker._bounded_process_communicate",
                return_value=(
                    _worker_payload(command_id="isolated").encode("utf-8"),
                    b"",
                    False,
                    False,
                ),
            ):
                result = worker.execute(
                    TerminalCommand(
                        id="isolated",
                        command="echo",
                        args=["ok"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertTrue(result.success)
            launch = sandbox.spawn_calls[0]
            self.assertEqual(launch["arguments"][0], str(sandbox.interpreter))
            self.assertEqual(launch["cwd"], sandbox.code_root / "src")
            self.assertLess(order.index("attach"), order.index("resume"))
        finally:
            worker.close()

    def test_isolated_setup_failure_never_falls_back_to_direct_spawn(self):
        sandbox = _FakeTerminalSandbox([], fail_stage=RuntimeError("stage failed"))
        worker = TerminalWorker(
            os_isolation=True,
            macos_sandbox_factory=lambda: sandbox,
        )
        try:
            with patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
                result = worker.execute(
                    TerminalCommand(
                        id="isolated",
                        command="echo",
                        args=["blocked"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertFalse(result.success)
            self.assertIn("stage", result.stderr.lower())
            popen.assert_not_called()
            self.assertTrue(sandbox.closed)
        finally:
            worker.close()

    def test_isolated_spawn_failure_closes_platform_sandbox(self):
        sandbox = _FakeTerminalSandbox(
            [], spawn_error=RuntimeError("spawn failed")
        )
        worker = TerminalWorker(
            os_isolation=True,
            macos_sandbox_factory=lambda: sandbox,
        )
        try:
            with patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
                result = worker.execute(
                    TerminalCommand(
                        id="spawn-failure",
                        command="echo",
                        args=["blocked"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertFalse(result.success)
            self.assertIn("spawn failed", result.stderr)
            popen.assert_not_called()
            self.assertTrue(sandbox.closed)
        finally:
            worker.close()

    def test_isolated_resume_failure_releases_containment_before_sandbox(self):
        order: list[str] = []
        sandbox = _FakeTerminalSandbox(order)
        worker = TerminalWorker(
            os_isolation=True,
            container_factory=lambda: sandbox,
        )

        class _ResumeFailingProcess(_IsolatedWorkerProcess):
            def resume(self) -> None:
                self.order.append("resume")
                raise WorkerContainerError("resume failed")

        def spawn(arguments, *, cwd, environment, **keywords):
            order.append("spawn")
            sandbox.spawn_calls.append(
                {
                    "arguments": list(arguments),
                    "cwd": cwd,
                    "environment": dict(environment),
                    "keywords": dict(keywords),
                }
            )
            process = _ResumeFailingProcess(
                _worker_payload(command_id="isolated").encode("utf-8"), order
            )
            sandbox.processes.append(process)
            return process

        sandbox.spawn = spawn

        def attach(_process):
            order.append("attach")
            return _RecordingContainment()

        try:
            with patch(
                "core.kernel.terminal_worker.os.name", "nt"
            ), patch(
                "core.kernel.terminal_worker.ProcessTreeContainment.attach",
                side_effect=attach,
            ):
                result = worker.execute(
                    TerminalCommand(
                        id="resume-failure",
                        command="echo",
                        args=["blocked"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertFalse(result.success)
            self.assertIn("resume failed", result.stderr)
            self.assertTrue(sandbox.closed)
            self.assertIsNone(worker._os_sandbox)
            self.assertLess(order.index("attach"), order.index("resume"))
            self.assertLess(order.index("resume"), order.index("sandbox-close"))
            self.assertEqual(sandbox.processes[0].close_spawn_handle_calls, 1)
        finally:
            if not worker._closed:
                worker.close()

    def test_isolated_containment_failure_closes_platform_sandbox(self):
        order: list[str] = []
        sandbox = _FakeTerminalSandbox(order)
        worker = TerminalWorker(
            os_isolation=True,
            macos_sandbox_factory=lambda: sandbox,
        )

        def attach(_process):
            order.append("attach")
            raise ProcessContainmentError("containment failed")

        try:
            with patch(
                "core.kernel.terminal_worker.ProcessTreeContainment.attach",
                side_effect=attach,
            ):
                result = worker.execute(
                    TerminalCommand(
                        id="containment-failure",
                        command="echo",
                        args=["blocked"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertFalse(result.success)
            self.assertIn("containment failed", result.stderr)
            self.assertTrue(sandbox.closed)
            self.assertIsNone(worker._os_sandbox)
            self.assertEqual(sandbox.processes[0].close_spawn_handle_calls, 1)
        finally:
            if not worker._closed:
                worker.close()

    def test_explicit_isolation_on_an_unsupported_platform_fails_without_direct_spawn(self):
        worker = TerminalWorker(os_isolation=True)
        try:
            with patch("core.kernel.terminal_worker.os.name", "posix"), patch(
                "core.kernel.terminal_worker.sys.platform", "freebsd"
            ), patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
                result = worker.execute(
                    TerminalCommand(
                        id="unsupported",
                        command="echo",
                        args=["blocked"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertFalse(result.success)
            self.assertIn("isolation", result.stderr.lower())
            popen.assert_not_called()
        finally:
            worker.close()

    def test_platform_sandbox_cleanup_is_retained_for_retry(self):
        sandbox = _FakeTerminalSandbox(
            [], close_errors=[WorkerContainerError("busy"), None]
        )
        worker = TerminalWorker(os_isolation=True)
        worker._os_sandbox = sandbox
        worker._os_sandbox_platform = "windows"
        try:
            with self.assertRaisesRegex(RuntimeError, "OS sandbox"):
                worker.close()

            self.assertFalse(worker._closed)
            self.assertIs(worker._os_sandbox, sandbox)

            worker.close()
            self.assertTrue(worker._closed)
            self.assertIsNone(worker._os_sandbox)
            self.assertTrue(sandbox.closed)
        finally:
            if not worker._closed:
                worker.close()

    def test_worker_response_overflow_kills_child_before_decode(self):
        worker = TerminalWorker()
        payload = _worker_payload(stdout="x" * WORKER_RESPONSE_LIMIT).encode("utf-8")
        process = _PendingWorkerProcess(payload)
        with patch(
            "core.kernel.terminal_worker.subprocess.Popen",
            return_value=process,
        ):
            try:
                result = worker.execute(
                    TerminalCommand(
                        id="overflow",
                        command="echo",
                        risk_level=CommandRisk.SAFE,
                    )
                )
            finally:
                worker.close()

        self.assertFalse(result.success)
        self.assertIn("response exceeds", result.stderr.lower())
        self.assertEqual(process.kill_calls, 1)

    def test_worker_child_applies_resource_budgets_before_the_request(self):
        order: list[str] = []
        payload = json.dumps(
            {
                "command_id": "budget",
                "command": "echo",
                "args": ["ok"],
                "timeout": 5,
                "risk_level": "safe",
            }
        ).encode("utf-8")
        stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch(
                "core.kernel.terminal_worker.apply_worker_resource_limits",
                side_effect=lambda: order.append("limits"),
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_network"
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_filesystem"
            ), patch(
                "core.kernel.terminal_worker._read_worker_request",
                side_effect=lambda: (order.append("request"), {
                    "command_id": "budget",
                    "command": "echo",
                    "args": ["ok"],
                    "timeout": 5,
                    "risk_level": "safe",
                })[1],
            ), patch("core.kernel.terminal_worker.sys.stdin", stdin), patch(
                "core.kernel.terminal_worker.sys.stdout", stdout
            ):
                self.assertEqual(_worker_main(), 0)
        finally:
            stdin.detach()

        self.assertEqual(order, ["limits", "request"])

    def test_worker_child_fails_closed_when_budgets_cannot_be_enforced(self):
        stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch(
                "core.kernel.terminal_worker.apply_worker_resource_limits",
                side_effect=WorkerResourceLimitError("denied"),
            ), patch(
                "core.kernel.terminal_worker._read_worker_request",
            ) as read_request, patch(
                "core.kernel.terminal_worker.sys.stdin", stdin
            ), patch("core.kernel.terminal_worker.sys.stdout", stdout):
                self.assertEqual(_worker_main(), 0)

            read_request.assert_not_called()
        finally:
            stdin.detach()

        result = json.loads(stdout.getvalue())
        self.assertFalse(result["success"])
        self.assertIn("denied", result["stderr"])

    def test_worker_child_applies_os_isolation_before_the_request(self):
        order: list[str] = []
        stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch(
                "core.kernel.terminal_worker.apply_worker_resource_limits",
                side_effect=lambda: order.append("limits"),
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_network",
                side_effect=lambda: order.append("network"),
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_filesystem",
                side_effect=lambda _root, root_writable=False: order.append(
                    f"filesystem:{root_writable}"
                ),
            ), patch(
                "core.kernel.terminal_worker._read_worker_request",
                side_effect=lambda: (order.append("request"), {
                    "command_id": "isolated",
                    "command": "echo",
                    "args": ["ok"],
                    "timeout": 5,
                    "risk_level": "safe",
                })[1],
            ), patch("core.kernel.terminal_worker.sys.stdin", stdin), patch(
                "core.kernel.terminal_worker.sys.stdout", stdout
            ):
                self.assertEqual(_worker_main(), 0)
        finally:
            stdin.detach()

        self.assertEqual(
            order, ["limits", "network", "filesystem:True", "request"]
        )

    def test_worker_child_binds_tempfile_to_the_authorized_sandbox_root(self):
        sandbox = Path(tempfile.mkdtemp(prefix=".test-worker-temp-root-"))
        request = {
            "command_id": "temp-root",
            "command": "echo",
            "args": ["ok"],
            "timeout": 5,
            "risk_level": "safe",
        }
        stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch(
                "core.kernel.terminal_worker.apply_worker_resource_limits"
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_network"
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_filesystem"
            ), patch(
                "core.kernel.terminal_worker._worker_sandbox_path",
                return_value=sandbox,
            ), patch(
                "core.kernel.terminal_worker._read_worker_request",
                return_value=request,
            ), patch("core.kernel.terminal_worker.sys.stdin", stdin), patch(
                "core.kernel.terminal_worker.sys.stdout", stdout
            ), patch("core.kernel.terminal_worker.tempfile.tempdir", None):
                self.assertEqual(_worker_main(), 0)
                self.assertEqual(
                    __import__("tempfile").tempdir,
                    None,
                )
        finally:
            stdin.detach()
            shutil.rmtree(sandbox, ignore_errors=True)

    def test_worker_sandbox_path_prefers_explicit_tmpdir_on_windows(self):
        with patch("core.kernel.terminal_worker.os.name", "nt"), patch.dict(
            os.environ,
            {"TEMP": "C:\\virtual-temp", "TMPDIR": "C:\\authorized-temp"},
            clear=True,
        ), patch(
            "core.kernel.terminal_worker.Path",
            side_effect=PureWindowsPath,
        ):
            self.assertEqual(
                _worker_sandbox_path(), PureWindowsPath("C:\\authorized-temp")
            )

    def test_worker_child_drops_identity_after_os_isolation(self):
        order: list[str] = []
        stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch(
                "core.kernel.terminal_worker._drop_worker_privileges",
                side_effect=lambda: order.append("drop"),
            ), patch(
                "core.kernel.terminal_worker.apply_worker_resource_limits",
                side_effect=lambda: order.append("limits"),
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_network",
                side_effect=lambda: order.append("network"),
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_filesystem",
                side_effect=lambda _root, root_writable=False: order.append(
                    f"filesystem:{root_writable}"
                ),
            ), patch(
                "core.kernel.terminal_worker._read_worker_request",
                side_effect=lambda: (order.append("request"), {
                    "command_id": "identity-order",
                    "command": "echo",
                    "args": ["ok"],
                    "timeout": 5,
                    "risk_level": "safe",
                })[1],
            ), patch("core.kernel.terminal_worker.sys.stdin", stdin), patch(
                "core.kernel.terminal_worker.sys.stdout", stdout
            ):
                self.assertEqual(_worker_main(), 0)
        finally:
            stdin.detach()

        self.assertEqual(
            order,
            ["limits", "network", "filesystem:True", "drop", "request"],
        )

    def test_worker_child_fails_closed_when_network_isolation_fails(self):
        stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch(
                "core.kernel.terminal_worker.apply_worker_resource_limits"
            ), patch(
                "core.kernel.terminal_worker.isolate_worker_network",
                side_effect=WorkerNetworkIsolationError("network denied"),
            ), patch(
                "core.kernel.terminal_worker._read_worker_request"
            ) as read_request, patch("core.kernel.terminal_worker.sys.stdin", stdin), patch(
                "core.kernel.terminal_worker.sys.stdout", stdout
            ):
                self.assertEqual(_worker_main(), 0)

            read_request.assert_not_called()
        finally:
            stdin.detach()

        result = json.loads(stdout.getvalue())
        self.assertFalse(result["success"])
        self.assertIn("network denied", result["stderr"])

    def test_worker_child_fails_closed_when_filesystem_isolation_fails(self):
        stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch(
                "core.kernel.terminal_worker.apply_worker_resource_limits"
            ), patch("core.kernel.terminal_worker.isolate_worker_network"), patch(
                "core.kernel.terminal_worker.isolate_worker_filesystem",
                side_effect=WorkerFilesystemIsolationError("filesystem denied"),
            ), patch(
                "core.kernel.terminal_worker._read_worker_request"
            ) as read_request, patch("core.kernel.terminal_worker.sys.stdin", stdin), patch(
                "core.kernel.terminal_worker.sys.stdout", stdout
            ):
                self.assertEqual(_worker_main(), 0)

            read_request.assert_not_called()
        finally:
            stdin.detach()

        result = json.loads(stdout.getvalue())
        self.assertFalse(result["success"])
        self.assertIn("filesystem denied", result["stderr"])

    def test_worker_launch_requests_its_own_process_group(self):
        worker = TerminalWorker()
        with patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
            popen.return_value.communicate.return_value = (_worker_payload(), "")
            popen.return_value.returncode = 0
            try:
                worker.execute(
                    TerminalCommand(
                        id="wire",
                        command="echo",
                        risk_level=CommandRisk.SAFE,
                    )
                )
            finally:
                worker.close()

        kwargs = popen.call_args.kwargs
        for name, value in process_group_popen_kwargs().items():
            self.assertEqual(kwargs[name], value)

    def test_worker_timeout_terminates_and_confirms_the_owned_tree(self):
        worker = TerminalWorker()
        process = _PendingWorkerProcess(b"")
        containment = _RecordingContainment()
        with patch(
            "core.kernel.terminal_worker.subprocess.Popen",
            return_value=process,
        ), patch(
            "core.kernel.terminal_worker.ProcessTreeContainment.attach",
            return_value=containment,
        ), patch(
            "core.kernel.terminal_worker._bounded_process_communicate",
            return_value=(b"", b"", True, False),
        ):
            try:
                result = worker.execute(
                    TerminalCommand(
                        id="timeout",
                        command="echo",
                        timeout=1,
                        risk_level=CommandRisk.SAFE,
                    )
                )
            finally:
                worker.close()

        self.assertFalse(result.success)
        self.assertIn("timed out", result.stderr.lower())
        self.assertTrue(containment.terminated)
        self.assertTrue(containment.waited)
        self.assertTrue(containment.closed)

    def test_successful_worker_release_failure_is_reported(self):
        class _StuckContainment(_RecordingContainment):
            releasable = False

            def wait_empty(self, _timeout: float) -> bool:
                self.waited = True
                return self.releasable

        worker = TerminalWorker()
        process = _PendingWorkerProcess(_worker_payload().encode("utf-8"))
        containment = _StuckContainment()
        with patch(
            "core.kernel.terminal_worker.subprocess.Popen",
            return_value=process,
        ), patch(
            "core.kernel.terminal_worker.ProcessTreeContainment.attach",
            return_value=containment,
        ), patch(
            "core.kernel.terminal_worker._bounded_process_communicate",
            return_value=(_worker_payload(), "", False, False),
        ):
            result = worker.execute(
                TerminalCommand(
                    id="wire",
                    command="echo",
                    risk_level=CommandRisk.SAFE,
                )
            )

        self.assertFalse(result.success)
        self.assertIn("could not be released", result.stderr.lower())
        self.assertFalse(containment.closed)
        with self.assertRaisesRegex(RuntimeError, "could not be released"):
            worker.close()
        containment.releasable = True
        worker.close()
        self.assertTrue(containment.closed)

    def test_worker_rejects_parent_request_beyond_wire_limit_before_launch(self):
        worker = TerminalWorker()
        try:
            with patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
                result = worker.execute(
                    TerminalCommand(
                        id="x" * WORKER_REQUEST_LIMIT,
                        command="echo",
                        risk_level=CommandRisk.SAFE,
                    )
                )

            self.assertFalse(result.success)
            self.assertIn("request exceeds", result.stderr.lower())
            popen.assert_not_called()
        finally:
            worker.close()

    def test_failed_worker_release_remains_owned_until_close_retry(self):
        class _RetryContainment(_RecordingContainment):
            def __init__(self) -> None:
                super().__init__()
                self.wait_empty_calls = 0

            def wait_empty(self, _timeout: float) -> bool:
                self.wait_empty_calls += 1
                return self.wait_empty_calls >= 3

        worker = TerminalWorker()
        process = _PendingWorkerProcess(_worker_payload().encode("utf-8"))
        containment = _RetryContainment()
        with patch(
            "core.kernel.terminal_worker.subprocess.Popen",
            return_value=process,
        ), patch(
            "core.kernel.terminal_worker.ProcessTreeContainment.attach",
            return_value=containment,
        ), patch(
            "core.kernel.terminal_worker._bounded_process_communicate",
            return_value=(_worker_payload(), "", False, False),
        ):
            result = worker.execute(
                TerminalCommand(
                    id="wire",
                    command="echo",
                    risk_level=CommandRisk.SAFE,
                )
            )

        self.assertFalse(result.success)
        self.assertFalse(containment.closed)
        worker.close()
        self.assertTrue(containment.closed)
        self.assertEqual(containment.wait_empty_calls, 3)

    def test_worker_request_rejects_input_beyond_wire_limit(self):
        payload = json.dumps(
            {
                "command_id": "x" * (32 * 1024),
                "command": "echo",
                "args": ["ok"],
                "timeout": 5,
                "risk_level": "safe",
            }
        ).encode("utf-8")
        stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        stdout = io.StringIO()
        try:
            with patch("core.kernel.terminal_worker.isolate_worker_network"), patch(
                "core.kernel.terminal_worker.isolate_worker_filesystem"
            ), patch("core.kernel.terminal_worker.sys.stdin", stdin), patch(
                "core.kernel.terminal_worker.sys.stdout", stdout
            ):
                self.assertEqual(_worker_main(), 0)
        finally:
            stdin.detach()

        result = json.loads(stdout.getvalue())
        self.assertFalse(result["success"])
        self.assertEqual(result["command_id"], "worker")
        self.assertIn("input limit", result["stderr"])

    def test_close_waits_for_inflight_worker_before_sandbox_cleanup(self):
        worker = TerminalWorker()
        sandbox_dir = worker.sandbox_dir
        command_started = threading.Event()
        release_command = threading.Event()
        close_finished = threading.Event()
        command_result = {}

        def communicate(*_args, **_kwargs):
            command_started.set()
            release_command.wait(timeout=5)
            return (
                _worker_payload(command_id="inflight", risk_level="safe"),
                "",
            )

        with patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
            popen.return_value.communicate.side_effect = communicate
            popen.return_value.returncode = 0
            command_thread = threading.Thread(
                target=lambda: command_result.setdefault(
                    "value",
                    worker.execute(
                        TerminalCommand(
                            id="inflight",
                            command="echo",
                            risk_level=CommandRisk.SAFE,
                        )
                    ),
                )
            )
            close_thread = threading.Thread(
                target=lambda: (worker.close(), close_finished.set())
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
                worker.close()

        self.assertTrue(close_finished.is_set())
        self.assertTrue(command_result["value"].success)
        self.assertFalse(sandbox_dir.exists())

    def test_concurrent_close_calls_cleanup_once(self):
        worker = TerminalWorker()
        sandbox_directory = worker._sandbox_directory
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()
        close_errors = []

        def cleanup():
            cleanup_started.set()
            release_cleanup.wait(timeout=5)

        def close_worker():
            try:
                worker.close()
            except Exception as error:
                close_errors.append(error)

        with patch.object(sandbox_directory, "cleanup", side_effect=cleanup) as cleanup_mock:
            first_close = threading.Thread(target=close_worker)
            second_close = threading.Thread(target=close_worker)
            try:
                first_close.start()
                self.assertTrue(cleanup_started.wait(timeout=5))
                second_close.start()
                second_close.join(timeout=0.1)
            finally:
                release_cleanup.set()
                first_close.join(timeout=5)
                second_close.join(timeout=5)

            self.assertEqual(close_errors, [])
            self.assertEqual(cleanup_mock.call_count, 1)

        sandbox_directory.cleanup()

    def test_concurrent_close_waiters_share_inflight_cleanup(self):
        worker = TerminalWorker()
        sandbox_directory = worker._sandbox_directory
        command_started = threading.Event()
        release_command = threading.Event()

        def communicate(*_args, **_kwargs):
            command_started.set()
            release_command.wait(timeout=5)
            return (
                _worker_payload(command_id="inflight", risk_level="safe"),
                "",
            )

        with patch("core.kernel.terminal_worker.subprocess.Popen") as popen, patch.object(
            sandbox_directory,
            "cleanup",
        ) as cleanup:
            popen.return_value.communicate.side_effect = communicate
            popen.return_value.returncode = 0
            command_thread = threading.Thread(
                target=lambda: worker.execute(
                    TerminalCommand(
                        id="inflight",
                        command="echo",
                        risk_level=CommandRisk.SAFE,
                    )
                )
            )
            first_close = threading.Thread(target=worker.close)
            second_close = threading.Thread(target=worker.close)
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

            self.assertEqual(cleanup.call_count, 1)

        sandbox_directory.cleanup()

    def test_cleanup_failure_keeps_worker_open_for_close_retry(self):
        worker = TerminalWorker()
        sandbox_directory = worker._sandbox_directory
        sandbox_path = worker.sandbox_dir

        with patch.object(
            sandbox_directory,
            "cleanup",
            side_effect=[OSError("sandbox is busy"), None],
        ) as cleanup:
            with self.assertRaisesRegex(OSError, "sandbox is busy"):
                worker.close()

            self.assertFalse(worker._closed)
            self.assertEqual(worker.sandbox_dir, sandbox_path)

            worker.close()

        self.assertEqual(cleanup.call_count, 2)
        self.assertTrue(worker._closed)
        self.assertIsNone(worker.sandbox_dir)
        sandbox_directory.cleanup()

    def test_worker_response_rejects_type_coercion_and_invalid_invariants(self):
        worker = TerminalWorker()
        command = TerminalCommand(
            id="wire",
            command="echo",
            risk_level=CommandRisk.SAFE,
        )
        cases = {
            "string success": _worker_payload(success="false"),
            "fractional exit code": _worker_payload(exit_code=0.5),
            "negative duration": _worker_payload(duration=-0.1),
            "invalid timestamp": _worker_payload(timestamp="not-a-timestamp"),
            "inconsistent success": _worker_payload(success=False, exit_code=0),
        }
        try:
            for name, payload in cases.items():
                with self.subTest(name=name):
                    result = worker._decode_result(command, payload)
                    self.assertFalse(result.success)
                    self.assertEqual(result.exit_code, -1)
                    self.assertEqual(result.command_id, command.id)
                    self.assertEqual(result.risk_level, command.risk_level.value)
                    self.assertIn("Invalid worker response", result.stderr)
        finally:
            worker.close()

    def test_worker_response_rejects_schema_and_correlation_drift(self):
        worker = TerminalWorker()
        command = TerminalCommand(
            id="wire",
            command="echo",
            risk_level=CommandRisk.SAFE,
        )
        missing_timestamp = json.loads(_worker_payload())
        del missing_timestamp["timestamp"]
        duplicate_success = (
            '{"command_id":"wire","exit_code":0,"stdout":"ok","stderr":"",'
            '"duration":0.1,"success":false,"success":true,"risk_level":"safe",'
            f'"timestamp":"{_WORKER_TIMESTAMP}"}}'
        )
        cases = {
            "missing field": json.dumps(missing_timestamp),
            "unknown field": _worker_payload(extra="value"),
            "command mismatch": _worker_payload(command_id="other"),
            "risk mismatch": _worker_payload(risk_level="dangerous"),
            "duplicate key": duplicate_success,
            "non-finite duration": _worker_payload(duration=float("nan")),
            "excessive nesting": "[" * 5_000 + "0" + "]" * 5_000,
        }
        try:
            for name, payload in cases.items():
                with self.subTest(name=name):
                    result = worker._decode_result(command, payload)
                    self.assertFalse(result.success)
                    self.assertEqual(result.exit_code, -1)
                    self.assertEqual(result.command_id, command.id)
                    self.assertEqual(result.risk_level, command.risk_level.value)
                    self.assertIn("Invalid worker response", result.stderr)
        finally:
            worker.close()

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
            worker_path = Path(result.stdout.strip())
            self.assertTrue(worker_path.is_absolute())
            self.assertTrue(worker_path.is_dir())
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

        explicit = TerminalExecutor(sandbox=False, allow_caller_context=True)
        state = main.AppState(terminal=explicit)
        self.assertIs(state.terminal, explicit)

        explicit_fastapi = TerminalExecutor(sandbox=False, allow_caller_context=True)
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
                    f'"timestamp":"{_WORKER_TIMESTAMP}"}}',
                )
                popen.return_value.returncode = 0
                worker.execute(TerminalCommand(id="x", command="echo", args=["ok"], timeout=5))
                environment = popen.call_args.kwargs["env"]
                self.assertNotIn("JARVIS_TERMINAL_TOKEN", environment)
                self.assertNotIn("JARVIS_TEST_SECRET", environment)
                self.assertEqual(environment["PYTHONPATH"], str(Path(__file__).parent.parent / "src"))
        finally:
            worker.close()

    def test_worker_launch_disables_python_startup_hooks(self):
        worker = TerminalWorker()
        try:
            with patch("core.kernel.terminal_worker.subprocess.Popen") as popen:
                popen.return_value.communicate.return_value = (
                    _worker_payload(),
                    "",
                )
                popen.return_value.returncode = 0
                worker.execute(
                    TerminalCommand(
                        id="startup-hooks",
                        command="echo",
                        args=["ok"],
                        risk_level=CommandRisk.SAFE,
                    )
                )

            command = popen.call_args.args[0]
            self.assertEqual(
                command,
                [
                    sys.executable,
                    "-S",
                    "-m",
                    "core.kernel.terminal_worker",
                    "--worker",
                ],
            )
            environment = popen.call_args.kwargs["env"]
            self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        finally:
            worker.close()

    def test_worker_audit_history_evicts_oldest_entries(self):
        worker = TerminalWorker()
        try:
            for index in range(1005):
                result = worker.execute(
                    TerminalCommand(
                        id=f"worker-{index}",
                        command="echo",
                        env={"BLOCKED": "1"},
                        risk_level=CommandRisk.SAFE,
                    )
                )
                self.assertFalse(result.success)

            audit_log = worker.get_audit_log(limit=5000)

            self.assertEqual(len(audit_log), 1000)
            self.assertEqual(audit_log[0]["command_id"], "worker-5")
            self.assertEqual(audit_log[-1]["command_id"], "worker-1004")
        finally:
            worker.close()

    def test_worker_audit_snapshots_do_not_alias_internal_entries(self):
        worker = TerminalWorker()
        try:
            worker.execute(TerminalCommand(id="audit", command="pwd", timeout=5))
            snapshot = worker.get_audit_log(limit=1)
            snapshot[0]["command_id"] = "tampered"

            self.assertEqual(
                worker.get_audit_log(limit=1)[0]["command_id"],
                "audit",
            )
        finally:
            worker.close()

    def test_worker_audit_limit_is_a_non_negative_plain_integer(self):
        worker = TerminalWorker()
        try:
            self.assertEqual(worker.get_audit_log(limit=0), [])
            for invalid_limit in (-1, True, 1.5, "1"):
                with self.subTest(limit=invalid_limit):
                    with self.assertRaisesRegex(ValueError, "non-negative integer"):
                        worker.get_audit_log(limit=invalid_limit)

            worker.clear_audit_log()
            self.assertEqual(worker.get_audit_log(), [])
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
