import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import time
from threading import Thread
import unittest

from core.brain.role_worker import (
    RoleWorkerSupervisor,
    WorkerTaskTerminalError,
    apply_worker_token_usage,
    execute_role_task,
)
from core.contracts.worker_protocol import (
    WorkerEvent,
    WorkerEventKind,
    WorkerTaskRequest,
    WorkerTaskStatus,
)
from tests import worker_fixtures


class _OllamaWorkerFixture(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps(
            {
                "model": "fixture-model:latest",
                "message": {"role": "assistant", "content": "WORKER OK"},
                "done": True,
                "prompt_eval_count": 11,
                "eval_count": 7,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestRoleWorkerSupervisor(unittest.TestCase):
    def setUp(self):
        self.supervisors = []

    def tearDown(self):
        for supervisor in self.supervisors:
            supervisor.shutdown()
            self.assertEqual(supervisor.active_process_count(), 0)

    def make_supervisor(self, runner, **kwargs):
        supervisor = RoleWorkerSupervisor(runner, **kwargs)
        self.supervisors.append(supervisor)
        return supervisor

    def wait_terminal(self, supervisor, task_id, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = supervisor.get(task_id)
            if record is not None and record.status.is_terminal:
                return record
            time.sleep(0.02)
        self.fail(f"task {task_id} did not reach a terminal state")

    def test_success_is_published_only_after_process_exit(self):
        supervisor = self.make_supervisor(
            worker_fixtures.succeed,
            runner_config={"marker": "child"},
        )
        request = WorkerTaskRequest.new("engineer", "review", 10)

        submitted = supervisor.submit(request)
        terminal = self.wait_terminal(supervisor, request.task_id)

        self.assertEqual(submitted.status, WorkerTaskStatus.RUNNING)
        self.assertEqual(terminal.status, WorkerTaskStatus.SUCCEEDED)
        self.assertEqual(terminal.result["marker"], "child")
        self.assertTrue(terminal.termination_confirmed)
        self.assertEqual(supervisor.active_process_count(), 0)

    def test_runner_exception_and_abrupt_exit_are_distinct(self):
        failed_supervisor = self.make_supervisor(worker_fixtures.fail)
        failed_request = WorkerTaskRequest.new("engineer", "fail", 10)
        failed_supervisor.submit(failed_request)

        crashed_supervisor = self.make_supervisor(worker_fixtures.crash)
        crashed_request = WorkerTaskRequest.new("engineer", "crash", 10)
        crashed_supervisor.submit(crashed_request)

        failed = self.wait_terminal(failed_supervisor, failed_request.task_id)
        crashed = self.wait_terminal(crashed_supervisor, crashed_request.task_id)

        self.assertEqual(failed.status, WorkerTaskStatus.FAILED)
        self.assertIn("fixture runner failed", failed.error)
        self.assertEqual(crashed.status, WorkerTaskStatus.CRASHED)
        self.assertIn("exit code 17", crashed.error)

    def test_timeout_and_cancel_wait_for_confirmed_process_exit(self):
        timeout_supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 5},
            termination_grace=0.5,
        )
        timeout_request = WorkerTaskRequest.new("engineer", "timeout", 1)
        timeout_supervisor.submit(timeout_request)
        timed_out = self.wait_terminal(timeout_supervisor, timeout_request.task_id)

        cancel_supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 5},
            termination_grace=0.5,
        )
        cancel_request = WorkerTaskRequest.new("engineer", "cancel", 10)
        cancel_supervisor.submit(cancel_request)
        cancelled = cancel_supervisor.cancel(cancel_request.task_id)

        self.assertEqual(timed_out.status, WorkerTaskStatus.TIMEOUT)
        self.assertTrue(timed_out.termination_confirmed)
        self.assertEqual(cancelled.status, WorkerTaskStatus.CANCELLED)
        self.assertTrue(cancelled.termination_confirmed)
        self.assertEqual(timeout_supervisor.active_process_count(), 0)
        self.assertEqual(cancel_supervisor.active_process_count(), 0)

    def test_unknown_and_terminal_cancellation_are_distinguished(self):
        supervisor = self.make_supervisor(worker_fixtures.succeed)
        self.assertIsNone(supervisor.cancel("task-missing"))
        request = WorkerTaskRequest.new("engineer", "done", 10)
        supervisor.submit(request)
        self.wait_terminal(supervisor, request.task_id)

        with self.assertRaises(WorkerTaskTerminalError):
            supervisor.cancel(request.task_id)

    def test_output_and_history_are_bounded(self):
        oversized = self.make_supervisor(
            worker_fixtures.oversized,
            runner_config={"size": 4096},
            max_output_bytes=256,
        )
        request = WorkerTaskRequest.new("engineer", "large", 10)
        oversized.submit(request)
        terminal = self.wait_terminal(oversized, request.task_id)
        self.assertEqual(terminal.status, WorkerTaskStatus.FAILED)
        self.assertIn("output limit", terminal.error)

        bounded = self.make_supervisor(worker_fixtures.succeed, max_records=2)
        for index in range(3):
            item = WorkerTaskRequest.new("engineer", f"task-{index}", 10)
            bounded.submit(item)
            self.wait_terminal(bounded, item.task_id)
        self.assertEqual(len(bounded.list()), 2)

    def test_late_event_cannot_change_terminal_record(self):
        supervisor = self.make_supervisor(worker_fixtures.succeed)
        request = WorkerTaskRequest.new("engineer", "done", 10)
        supervisor.submit(request)
        terminal = self.wait_terminal(supervisor, request.task_id)
        forged = WorkerEvent.new(
            request,
            sequence=terminal.last_event_sequence + 1,
            kind=WorkerEventKind.FAILURE,
            payload={"error": "late failure"},
        )

        accepted = supervisor._accept_event(request.task_id, forged)

        self.assertFalse(accepted)
        self.assertEqual(supervisor.get(request.task_id), terminal)

    def test_shutdown_terminates_all_live_children(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 30},
            termination_grace=0.5,
        )
        requests = [
            WorkerTaskRequest.new("engineer", f"sleep-{index}", 30)
            for index in range(2)
        ]
        for request in requests:
            supervisor.submit(request)

        supervisor.shutdown()

        self.assertEqual(supervisor.active_process_count(), 0)
        for request in requests:
            self.assertEqual(
                supervisor.get(request.task_id).status,
                WorkerTaskStatus.CANCELLED,
            )

    def test_fixed_role_runner_returns_content_and_parent_token_usage(self):
        from core.kernel.ollama_manager import OllamaManager

        server = HTTPServer(("127.0.0.1", 0), _OllamaWorkerFixture)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        parent_manager = OllamaManager(base_url=base_url)
        try:
            supervisor = self.make_supervisor(
                execute_role_task,
                runner_config={
                    "ollama_base_url": base_url,
                    "role_model": "fixture-model:latest",
                },
                on_terminal=lambda record: apply_worker_token_usage(
                    record,
                    parent_manager,
                ),
            )
            request = WorkerTaskRequest.new("engineer", "Use the fixture", 10)

            supervisor.submit(request)
            terminal = self.wait_terminal(supervisor, request.task_id)

            self.assertEqual(terminal.status, WorkerTaskStatus.SUCCEEDED)
            self.assertEqual(terminal.result["dispatch"]["message"], "WORKER OK")
            self.assertEqual(terminal.result["usage"]["prompt_tokens"], 11)
            self.assertEqual(terminal.result["usage"]["completion_tokens"], 7)
            usage = parent_manager.get_token_usage()
            self.assertEqual(usage.prompt_tokens, 11)
            self.assertEqual(usage.completion_tokens, 7)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
