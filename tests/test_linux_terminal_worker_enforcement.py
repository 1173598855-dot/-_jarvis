"""Real Linux enforcement probe for the production Terminal Worker chain."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Aggregate execution bootstraps this path before importing the module.
# ruff: noqa: E402
from core.kernel.worker_staging import stage_worker_tree

if __package__:
    from .test_linux_plugin_runtime_enforcement import (
        _collect_bounded_probe_output,
        _terminate_linux_probe_tree,
    )
else:
    from test_linux_plugin_runtime_enforcement import (
        _collect_bounded_probe_output,
        _terminate_linux_probe_tree,
    )

RUN_REAL_ENFORCEMENT = (
    sys.platform.startswith("linux")
    and os.environ.get("JARVIS_RUN_LINUX_TERMINAL_WORKER_ENFORCEMENT") == "1"
)
_DRIVER_TIMEOUT_SECONDS = 20
_DIAGNOSTIC_LIMIT = 8 * 1024
_PROBE_MODES = frozenset({"full", "filesystem-disabled", "network-disabled"})


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


@unittest.skipUnless(
    RUN_REAL_ENFORCEMENT,
    "requires an explicit real Linux Terminal Worker isolation run",
)
class TestLinuxTerminalWorkerEnforcement(unittest.TestCase):
    def test_production_terminal_worker_enforces_both_boundaries(self) -> None:
        payload = self._run_probe("full")

        self._assert_baseline(payload)
        self._assert_worker_lifecycle(payload)
        self.assertEqual(
            payload["restricted"],
            {
                "loopback": "denied",
                "outside_read": "denied",
                "outside_write": "denied",
                "source_read": "allowed",
                "source_write": "denied",
                "worker_write": "allowed",
            },
        )
        self.assertEqual(payload["outer_outside_content"], "baseline")
        self.assertEqual(payload["outer_source_marker_content"], "baseline")

    def test_probe_detects_a_missing_filesystem_boundary(self) -> None:
        payload = self._run_probe("filesystem-disabled")

        self._assert_baseline(payload)
        self._assert_worker_lifecycle(payload)
        self.assertEqual(
            payload["restricted"],
            {
                "loopback": "denied",
                "outside_read": "allowed",
                "outside_write": "allowed",
                "source_read": "allowed",
                "source_write": "allowed",
                "worker_write": "allowed",
            },
        )
        self.assertEqual(payload["outer_outside_content"], "forbidden")
        self.assertEqual(payload["outer_source_marker_content"], "forbidden")

    def test_probe_detects_a_missing_network_boundary(self) -> None:
        payload = self._run_probe("network-disabled")

        self._assert_baseline(payload)
        self._assert_worker_lifecycle(payload)
        self.assertEqual(
            payload["restricted"],
            {
                "loopback": "allowed",
                "outside_read": "denied",
                "outside_write": "denied",
                "source_read": "allowed",
                "source_write": "denied",
                "worker_write": "allowed",
            },
        )
        self.assertEqual(payload["outer_outside_content"], "baseline")
        self.assertEqual(payload["outer_source_marker_content"], "baseline")

    def _assert_baseline(self, payload: dict) -> None:
        self.assertEqual(
            payload["baseline"],
            {
                "gid": payload["probe_gid"],
                "loopback": "allowed",
                "outside_read": "allowed",
                "outside_write": "allowed",
                "source_write": "allowed",
                "uid": payload["probe_uid"],
            },
        )
        self.assertNotEqual(payload["probe_uid"], 65_534)
        self.assertNotEqual(payload["probe_gid"], 65_534)

    def _assert_worker_lifecycle(self, payload: dict) -> None:
        self.assertEqual(payload["driver_pid"], payload["outer_driver_pid"])
        self.assertGreater(payload["worker_pid"], 0)
        self.assertNotEqual(payload["driver_pid"], payload["worker_pid"])
        self.assertEqual(
            payload["result"],
            {
                "command_id": "terminal-linux-probe",
                "exit_code": 0,
                "risk_level": "safe",
                "stderr": "",
                "success": True,
            },
        )
        worker_path = Path(payload["worker_path"])
        self.assertEqual(worker_path.name, "terminal-probe.txt")
        self.assertTrue(worker_path.parent.name.startswith("jarvis-terminal-worker-"))
        self.assertTrue(payload["worker_exists_before_close"])
        self.assertFalse(payload["worker_alive_after_execute"])
        self.assertFalse(payload["outer_worker_alive_after_driver"])
        self.assertTrue(payload["worker_root_reclaimed"])

    def _run_probe(self, mode: str) -> dict:
        if mode not in _PROBE_MODES:
            raise ValueError(f"unknown probe mode: {mode}")

        with tempfile.TemporaryDirectory(
            prefix=".test-linux-terminal-worker-enforcement-"
        ) as temporary:
            root = Path(temporary)
            staged_source = root / "staged-src"
            stage_worker_tree(ROOT / "src", staged_source)
            source_marker = staged_source / ".test-terminal-source-marker"
            source_marker.write_text("baseline", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("baseline", encoding="utf-8")
            driver_root = root / "driver"
            driver_root.mkdir()
            driver_tmp = root / "driver-tmp"
            driver_tmp.mkdir()
            worker_pid_path = root / "worker.pid"
            worker_pid_path.write_text("", encoding="ascii")
            driver = driver_root / "probe_driver.py"
            driver.write_text(self._driver_source(), encoding="utf-8")
            child_shim = driver_root / "probe_worker.py"
            child_shim.write_text(self._child_shim_source(), encoding="utf-8")

            root.chmod(0o755)
            staged_source.chmod(0o755)
            source_marker.chmod(0o666)
            outside.chmod(0o666)
            driver_root.chmod(0o755)
            driver_tmp.chmod(0o777)
            worker_pid_path.chmod(0o666)
            driver.chmod(0o644)
            child_shim.chmod(0o644)

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            try:
                probe_uid = os.geteuid()
                probe_gid = os.getegid()
                demote = None
                if probe_uid == 0:
                    probe_uid = 12_345
                    probe_gid = 12_345

                    def demote() -> None:
                        os.setgroups([])
                        os.setgid(probe_gid)
                        os.setuid(probe_uid)

                environment = {
                    "PATH": os.environ.get("PATH", os.defpath),
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONPATH": str(staged_source),
                    "PYTHONUNBUFFERED": "1",
                    "TMPDIR": str(driver_tmp),
                }
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-S",
                        "-u",
                        str(driver),
                        mode,
                        str(outside),
                        str(source_marker),
                        str(listener.getsockname()[1]),
                        str(child_shim),
                        str(worker_pid_path),
                    ],
                    cwd=driver_root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=demote,
                    start_new_session=True,
                )
                abort_called = False
                cleanup_confirmed = True

                def abort() -> None:
                    nonlocal abort_called, cleanup_confirmed
                    if abort_called:
                        return
                    abort_called = True
                    cleanup_confirmed = _terminate_linux_probe_tree(
                        process,
                        worker_pid_path=worker_pid_path,
                    )

                try:
                    stdout, stderr, timed_out, output_limited = (
                        _collect_bounded_probe_output(
                            process,
                            timeout=_DRIVER_TIMEOUT_SECONDS,
                            stream_limit=_DIAGNOSTIC_LIMIT,
                            abort=abort,
                        )
                    )
                    diagnostic = stderr.decode("utf-8", errors="replace")
                    if timed_out:
                        self.fail(
                            "Linux Terminal Worker probe exceeded its "
                            f"{_DRIVER_TIMEOUT_SECONDS}-second deadline "
                            f"(cleanup_confirmed={cleanup_confirmed}): {diagnostic}"
                        )
                    if output_limited:
                        self.fail(
                            "Linux Terminal Worker probe output exceeded its "
                            f"{_DIAGNOSTIC_LIMIT}-byte per-stream limit "
                            f"(cleanup_confirmed={cleanup_confirmed})"
                        )
                    if process.returncode != 0:
                        abort()
                        self.fail(
                            f"probe exited {process.returncode} "
                            f"(cleanup_confirmed={cleanup_confirmed}): {diagnostic}"
                        )
                except BaseException:
                    abort()
                    raise
            finally:
                listener.close()

            try:
                payload = json.loads(stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                abort()
                self.fail(
                    "probe did not return one bounded UTF-8 JSON document: "
                    + stdout.decode("utf-8", errors="replace")
                )
            if type(payload) is not dict:
                self.fail("probe result must be a JSON object")

            worker_tokens = worker_pid_path.read_text(encoding="ascii").split()
            if len(worker_tokens) != 1 or not worker_tokens[0].isdigit():
                self.fail("probe did not record exactly one Worker PID")
            worker_pid = int(worker_tokens[0])
            payload.update({
                "outer_driver_pid": process.pid,
                "outer_outside_content": outside.read_text(encoding="utf-8"),
                "outer_source_marker_content": source_marker.read_text(encoding="utf-8"),
                "outer_worker_alive_after_driver": _process_is_alive(worker_pid),
                "probe_gid": probe_gid,
                "probe_uid": probe_uid,
            })
            return payload

    @staticmethod
    def _driver_source() -> str:
        return textwrap.dedent(
            """
            import json
            import os
            import socket
            import subprocess
            import sys
            from pathlib import Path

            from core.kernel import terminal_worker
            from core.kernel.terminal_executor import CommandRisk, TerminalCommand

            mode = sys.argv[1]
            outside = Path(sys.argv[2])
            source_marker = Path(sys.argv[3])
            port = int(sys.argv[4])
            child_shim = Path(sys.argv[5])
            worker_pid_path = Path(sys.argv[6])


            def attempt(operation):
                try:
                    operation()
                except OSError:
                    return "denied"
                return "allowed"


            def _process_is_alive(pid):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return False
                except OSError:
                    return True
                return True


            baseline = {
                "uid": os.geteuid(),
                "gid": os.getegid(),
                "outside_read": attempt(lambda: outside.read_text(encoding="utf-8")),
                "outside_write": attempt(
                    lambda: outside.write_text("baseline", encoding="utf-8")
                ),
                "source_write": attempt(
                    lambda: source_marker.write_text("baseline", encoding="utf-8")
                ),
                "loopback": attempt(
                    lambda: socket.create_connection(
                        ("127.0.0.1", port), timeout=1
                    ).close()
                ),
            }

            real_popen = subprocess.Popen
            expected_command = [
                sys.executable,
                "-S",
                "-m",
                "core.kernel.terminal_worker",
                terminal_worker.WORKER_FLAG,
            ]


            def spawn_probe(command, *args, **kwargs):
                if list(command) != expected_command:
                    raise RuntimeError(f"unexpected Terminal Worker command: {command!r}")
                replacement = [
                    sys.executable,
                    "-S",
                    "-u",
                    str(child_shim),
                    mode,
                    str(outside),
                    str(source_marker),
                    str(port),
                ]
                process = real_popen(replacement, *args, **kwargs)
                worker_pid_path.write_text(str(process.pid), encoding="ascii")
                return process


            terminal_worker.subprocess.Popen = spawn_probe
            worker = terminal_worker.TerminalWorker()
            worker_root = worker.sandbox_dir
            try:
                result = worker.execute(
                    TerminalCommand(
                        id="terminal-linux-probe",
                        command="echo",
                        args=["probe"],
                        timeout=5,
                        risk_level=CommandRisk.SAFE,
                    )
                )
                if not result.success:
                    raise RuntimeError(f"Terminal Worker failed: {result.stderr}")
                restricted_payload = json.loads(result.stdout)
                worker_path = Path(restricted_payload.pop("worker_path"))
                worker_pid = int(worker_pid_path.read_text(encoding="ascii"))
                payload = {
                    "baseline": baseline,
                    "driver_pid": os.getpid(),
                    "restricted": restricted_payload,
                    "result": {
                        "command_id": result.command_id,
                        "exit_code": result.exit_code,
                        "risk_level": result.risk_level,
                        "stderr": result.stderr,
                        "success": result.success,
                    },
                    "worker_alive_after_execute": _process_is_alive(worker_pid),
                    "worker_exists_before_close": worker_path.is_file(),
                    "worker_path": str(worker_path),
                    "worker_pid": worker_pid,
                }
            finally:
                worker.close()
                terminal_worker.subprocess.Popen = real_popen

            payload["worker_root_reclaimed"] = not worker_root.exists()
            print(json.dumps(payload, sort_keys=True), flush=True)
            """
        ).lstrip()

    @staticmethod
    def _child_shim_source() -> str:
        return textwrap.dedent(
            """
            import json
            import socket
            import sys
            from pathlib import Path

            from core.kernel import terminal_worker

            mode = sys.argv[1]
            outside = Path(sys.argv[2])
            source_marker = Path(sys.argv[3])
            port = int(sys.argv[4])

            if mode == "filesystem-disabled":
                terminal_worker.isolate_worker_filesystem = lambda *_args, **_kwargs: ()
            elif mode == "network-disabled":
                terminal_worker.isolate_worker_network = lambda **_kwargs: ()
            elif mode != "full":
                raise RuntimeError(f"unknown probe mode: {mode}")


            def attempt(operation):
                try:
                    operation()
                except OSError:
                    return "denied"
                return "allowed"


            def probe_operation(_command, _args, sandbox_dir):
                worker_path = sandbox_dir / "terminal-probe.txt"
                restricted = {
                    "outside_read": attempt(
                        lambda: outside.read_text(encoding="utf-8")
                    ),
                    "outside_write": attempt(
                        lambda: outside.write_text("forbidden", encoding="utf-8")
                    ),
                    "source_read": attempt(
                        lambda: source_marker.read_text(encoding="utf-8")
                    ),
                    "source_write": attempt(
                        lambda: source_marker.write_text("forbidden", encoding="utf-8")
                    ),
                    "loopback": attempt(
                        lambda: socket.create_connection(
                            ("127.0.0.1", port), timeout=1
                        ).close()
                    ),
                    "worker_write": attempt(
                        lambda: worker_path.write_text("allowed", encoding="utf-8")
                    ),
                    "worker_path": str(worker_path),
                }
                return json.dumps(restricted, sort_keys=True)


            terminal_worker._run_read_only_operation = probe_operation
            raise SystemExit(terminal_worker._worker_main())
            """
        ).lstrip()


if __name__ == "__main__":
    unittest.main()
