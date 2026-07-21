import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time
from threading import Thread
import unittest
from unittest.mock import Mock, patch

import core.brain.role_worker as role_worker_module
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

    def test_wait_returns_none_for_unknown_task(self):
        supervisor = self.make_supervisor(worker_fixtures.succeed)

        self.assertIsNone(supervisor.wait("task-missing", 0.1))

    def test_wait_returns_current_record_when_budget_expires(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 2},
        )
        request = WorkerTaskRequest.new("engineer", "still running", 10)
        supervisor.submit(request)

        started = time.monotonic()
        snapshot = supervisor.wait(request.task_id, 0.05)
        elapsed = time.monotonic() - started

        self.assertEqual(snapshot.task_id, request.task_id)
        self.assertEqual(snapshot.status, WorkerTaskStatus.RUNNING)
        self.assertGreaterEqual(elapsed, 0.04)

    def test_wait_is_notified_by_success_and_confirmed_timeout(self):
        success_supervisor = self.make_supervisor(worker_fixtures.succeed)
        success_request = WorkerTaskRequest.new("engineer", "succeed", 10)
        success_supervisor.submit(success_request)

        succeeded = success_supervisor.wait(success_request.task_id, 4)

        timeout_supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 5},
            termination_grace=0.05,
        )
        timeout_request = WorkerTaskRequest.new("reviewer", "timeout", 1)
        timeout_supervisor.submit(timeout_request)

        timed_out = timeout_supervisor.wait(timeout_request.task_id, 2)

        self.assertEqual(succeeded.status, WorkerTaskStatus.SUCCEEDED)
        self.assertTrue(succeeded.termination_confirmed)
        self.assertEqual(timed_out.status, WorkerTaskStatus.TIMEOUT)
        self.assertTrue(timed_out.termination_confirmed)

    def test_wait_rejects_invalid_timeout(self):
        supervisor = self.make_supervisor(worker_fixtures.succeed)

        for timeout in (-0.01, float("nan"), float("inf"), True, "1"):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(
                    ValueError,
                    "timeout must be a finite non-negative number",
                ):
                    supervisor.wait("task-missing", timeout)

    def test_terminal_wait_budget_covers_deadline_and_both_termination_graces(self):
        supervisor = self.make_supervisor(
            worker_fixtures.succeed,
            termination_grace=0.4,
        )

        self.assertEqual(supervisor.terminal_wait_budget(3), 4.05)
        for timeout_seconds in (0, 301, True, 1.0):
            with self.subTest(timeout_seconds=timeout_seconds):
                with self.assertRaisesRegex(
                    ValueError,
                    "timeout_seconds must be an integer from 1 through 300",
                ):
                    supervisor.terminal_wait_budget(timeout_seconds)

    def test_terminal_observers_are_isolated_and_run_outside_supervisor_lock(self):
        first_started = threading.Event()
        release_first = threading.Event()
        final_called = threading.Event()
        observer_calls = []

        def first_observer(record):
            observer_calls.append(("first", record.task_id))
            first_started.set()
            release_first.wait(timeout=4)

        def raising_observer(record):
            observer_calls.append(("raising", record.task_id))
            raise RuntimeError("observer failed")

        def final_observer(record):
            observer_calls.append(("final", record.task_id))
            final_called.set()

        supervisor = self.make_supervisor(
            worker_fixtures.succeed,
            on_terminal=first_observer,
        )
        supervisor.add_terminal_observer(raising_observer)
        supervisor.add_terminal_observer(final_observer)
        request = WorkerTaskRequest.new("engineer", "observe", 10)
        supervisor.submit(request)

        self.assertTrue(first_started.wait(timeout=4))
        outcomes = {}
        completed = {
            "get": threading.Event(),
            "list": threading.Event(),
            "wait": threading.Event(),
        }

        def call_api(name, operation):
            outcomes[name] = operation()
            completed[name].set()

        threads = [
            threading.Thread(
                target=call_api,
                args=("get", lambda: supervisor.get(request.task_id)),
                daemon=True,
            ),
            threading.Thread(
                target=call_api,
                args=("list", supervisor.list),
                daemon=True,
            ),
            threading.Thread(
                target=call_api,
                args=("wait", lambda: supervisor.wait(request.task_id, 1)),
                daemon=True,
            ),
        ]
        try:
            for thread in threads:
                thread.start()
            for name, event in completed.items():
                self.assertTrue(event.wait(timeout=1), f"{name} remained blocked")
            self.assertFalse(final_called.is_set())
        finally:
            release_first.set()
            for thread in threads:
                thread.join(timeout=2)

        self.assertTrue(final_called.wait(timeout=2))
        self.assertTrue(outcomes["get"].status.is_terminal)
        self.assertEqual(outcomes["list"][0], outcomes["get"])
        self.assertEqual(outcomes["wait"], outcomes["get"])
        self.assertEqual(
            observer_calls,
            [
                ("first", request.task_id),
                ("raising", request.task_id),
                ("final", request.task_id),
            ],
        )

    def test_terminal_observer_runs_before_record_can_be_pruned(self):
        publication_order = []

        def observe(record):
            publication_order.append(("observer", record.task_id))

        supervisor = self.make_supervisor(
            worker_fixtures.succeed,
            max_records=1,
            on_terminal=observe,
        )
        original_prune = supervisor._prune_records

        def track_prune():
            publication_order.append(("prune", None))
            original_prune()

        supervisor._prune_records = track_prune
        request = WorkerTaskRequest.new("engineer", "observer first", 10)
        supervisor.submit(request)

        terminal = self.wait_terminal(supervisor, request.task_id)
        deadline = time.monotonic() + 2
        while request.task_id in supervisor._runtimes and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(terminal.status, WorkerTaskStatus.SUCCEEDED)
        self.assertEqual(publication_order[0], ("observer", request.task_id))
        self.assertIn(("prune", None), publication_order)

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

    def test_unconfirmed_timeout_retains_runtime_and_blocks_role_reuse(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_crash,
            runner_config={"delay": 1.4},
            termination_grace=0.05,
        )
        request = WorkerTaskRequest.new("engineer", "timeout", 1)
        original_terminate = supervisor._terminate
        termination_attempted = threading.Event()
        call_lock = threading.Lock()
        terminate_calls = 0

        def fail_first_termination(process):
            nonlocal terminate_calls
            with call_lock:
                terminate_calls += 1
                call_number = terminate_calls
            if call_number == 1:
                termination_attempted.set()
                return False
            return original_terminate(process)

        supervisor._terminate = fail_first_termination
        supervisor.submit(request)
        self.assertTrue(termination_attempted.wait(4))

        error_deadline = time.monotonic() + 2
        snapshot = supervisor.get(request.task_id)
        while time.monotonic() < error_deadline and not snapshot.error:
            time.sleep(0.01)
            snapshot = supervisor.get(request.task_id)
        time.sleep(0.05)
        runtime_retained = request.task_id in supervisor._runtimes
        active_while_unconfirmed = supervisor.active_process_count()
        stable_snapshot = supervisor.get(request.task_id)

        replacement = WorkerTaskRequest.new("engineer", "replacement", 10)
        replacement_rejected = False
        try:
            supervisor.submit(replacement)
        except RuntimeError:
            replacement_rejected = True
        else:
            supervisor.cancel(replacement.task_id)

        terminal_deadline = time.monotonic() + 3
        terminal = supervisor.get(request.task_id)
        while time.monotonic() < terminal_deadline and not terminal.status.is_terminal:
            time.sleep(0.02)
            terminal = supervisor.get(request.task_id)

        self.assertEqual(snapshot.status, WorkerTaskStatus.RUNNING)
        self.assertEqual(
            snapshot.error,
            "Worker timeout could not confirm process termination",
        )
        self.assertFalse(snapshot.termination_confirmed)
        self.assertTrue(runtime_retained)
        self.assertEqual(active_while_unconfirmed, 1)
        self.assertEqual(stable_snapshot, snapshot)
        self.assertTrue(replacement_rejected)
        self.assertEqual(terminal.status, WorkerTaskStatus.TIMEOUT)
        self.assertTrue(terminal.termination_confirmed)

    def test_confirmed_terminal_allows_role_reuse_before_runtime_cleanup(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 10},
        )
        request = WorkerTaskRequest.new("engineer", "cancel before cleanup", 10)
        replacement = WorkerTaskRequest.new("engineer", "replacement", 10)
        original_cleanup = supervisor._cleanup_runtime
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()

        def pause_cleanup(task_id):
            if task_id == request.task_id:
                cleanup_started.set()
                release_cleanup.wait(timeout=4)
            original_cleanup(task_id)

        supervisor._cleanup_runtime = pause_cleanup
        submitted = None
        try:
            supervisor.submit(request)
            terminal = supervisor.cancel(request.task_id)
            self.assertTrue(cleanup_started.wait(timeout=2))

            submitted = supervisor.submit(replacement)
        finally:
            release_cleanup.set()
            supervisor._cleanup_runtime = original_cleanup
            supervisor.shutdown()

        self.assertEqual(terminal.status, WorkerTaskStatus.CANCELLED)
        self.assertTrue(terminal.termination_confirmed)
        self.assertEqual(submitted.status, WorkerTaskStatus.RUNNING)

    def test_missing_record_runtime_remains_fail_closed_until_shutdown(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 10},
        )
        request = WorkerTaskRequest.new("engineer", "missing record", 10)
        replacement = WorkerTaskRequest.new("engineer", "replacement", 10)
        supervisor.submit(request)
        runtime = supervisor._runtimes[request.task_id]
        missing_record_observed = threading.Event()

        class ObservedRecords(type(supervisor._records)):
            def get(self, key, default=None):
                value = super().get(key, default)
                if (
                    key == request.task_id
                    and key not in self
                    and threading.current_thread() is runtime.monitor
                ):
                    missing_record_observed.set()
                return value

        runtime_retained = False
        monitor_retained = False
        shutdown_cleaned = False
        monitor_stopped = False
        connection_closed = False

        try:
            with supervisor._lock:
                supervisor._records = ObservedRecords(supervisor._records)
                supervisor._records.pop(request.task_id)

            self.assertTrue(missing_record_observed.wait(timeout=2))
            runtime.monitor.join(timeout=0.2)
            with supervisor._lock:
                runtime_retained = request.task_id in supervisor._runtimes
            monitor_retained = runtime.monitor.is_alive()

            with self.assertRaisesRegex(
                RuntimeError,
                "termination is unconfirmed",
            ):
                supervisor.submit(replacement)

            supervisor.shutdown()
            runtime.monitor.join(timeout=2)
            monitor_stopped = not runtime.monitor.is_alive()
            connection_closed = runtime.connection.closed
            with supervisor._lock:
                shutdown_cleaned = request.task_id not in supervisor._runtimes
            try:
                process_stopped = not runtime.process.is_alive()
            except ValueError:
                process_stopped = True
            shutdown_cleaned = shutdown_cleaned and process_stopped
        finally:
            try:
                if runtime.process.is_alive():
                    runtime.process.terminate()
                    runtime.process.join(timeout=2)
            except ValueError:
                pass
            supervisor.shutdown()

        self.assertTrue(runtime_retained)
        self.assertTrue(monitor_retained)
        self.assertTrue(shutdown_cleaned)
        self.assertTrue(monitor_stopped)
        self.assertTrue(connection_closed)

    def test_shutdown_preserves_an_unconfirmed_timeout_intent(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 10},
            termination_grace=0.05,
        )
        request = WorkerTaskRequest.new("engineer", "timeout", 1)
        original_terminate = supervisor._terminate
        termination_attempted = threading.Event()
        terminate_calls = 0

        def fail_first_termination(process):
            nonlocal terminate_calls
            terminate_calls += 1
            if terminate_calls == 1:
                termination_attempted.set()
                return False
            return original_terminate(process)

        supervisor._terminate = fail_first_termination
        supervisor.submit(request)
        self.assertTrue(termination_attempted.wait(4))

        supervisor.shutdown()
        terminal = supervisor.get(request.task_id)

        self.assertEqual(terminal.status, WorkerTaskStatus.TIMEOUT)
        self.assertTrue(terminal.termination_confirmed)
        self.assertEqual(supervisor.active_process_count(), 0)

    def test_deadline_does_not_overwrite_a_concurrent_cancel_intent(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 10},
            termination_grace=0.05,
        )
        request = WorkerTaskRequest.new("engineer", "cancel race", 10)
        supervisor.submit(request)
        runtime = supervisor._runtimes[request.task_id]
        original_monotonic = role_worker_module.time.monotonic
        original_terminate = supervisor._terminate
        monitor_waiting = threading.Event()
        cancel_terminating = threading.Event()
        deadline_released = threading.Event()

        def controlled_monotonic():
            if (
                threading.current_thread() is runtime.monitor
                and not deadline_released.is_set()
            ):
                monitor_waiting.set()
                cancel_terminating.wait(timeout=2)
                deadline_released.set()
                return runtime.deadline + 1
            return original_monotonic()

        def leave_process_running(_process):
            if threading.current_thread().name == "cancel-race":
                cancel_terminating.set()
                deadline_released.wait(timeout=2)
            return False

        role_worker_module.time.monotonic = controlled_monotonic
        supervisor._terminate = leave_process_running
        cancel_thread = threading.Thread(
            target=supervisor.cancel,
            args=(request.task_id,),
            name="cancel-race",
            daemon=True,
        )
        try:
            self.assertTrue(monitor_waiting.wait(timeout=2))
            cancel_thread.start()
            cancel_thread.join(timeout=2)
            self.assertFalse(cancel_thread.is_alive())
            time.sleep(0.05)
            intent = runtime.termination_intent
        finally:
            role_worker_module.time.monotonic = original_monotonic
            supervisor._terminate = original_terminate
            supervisor.shutdown()

        self.assertEqual(intent, WorkerTaskStatus.CANCELLED)

    def test_exit_finalization_honors_a_concurrent_cancel_intent(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 0.2},
        )
        request = WorkerTaskRequest.new("engineer", "cancel after exit", 10)
        supervisor.submit(request)
        runtime = supervisor._runtimes[request.task_id]
        original_is_alive = runtime.process.is_alive
        original_terminate = supervisor._terminate
        monitor_observed_exit = threading.Event()
        release_monitor = threading.Event()
        cancel_intent_set = threading.Event()
        release_cancel = threading.Event()
        cancel_results = []
        cancel_errors = []

        def pause_monitor_at_exit():
            alive = original_is_alive()
            if (
                threading.current_thread() is runtime.monitor
                and not alive
                and not monitor_observed_exit.is_set()
            ):
                monitor_observed_exit.set()
                release_monitor.wait(timeout=4)
            return alive

        def pause_cancel_after_intent(process):
            if threading.current_thread().name == "cancel-after-exit":
                cancel_intent_set.set()
                release_cancel.wait(timeout=4)
            return original_terminate(process)

        def cancel_task():
            try:
                cancel_results.append(supervisor.cancel(request.task_id))
            except Exception as exc:
                cancel_errors.append(exc)

        runtime.process.is_alive = pause_monitor_at_exit
        supervisor._terminate = pause_cancel_after_intent
        cancel_thread = threading.Thread(
            target=cancel_task,
            name="cancel-after-exit",
            daemon=True,
        )
        try:
            self.assertTrue(monitor_observed_exit.wait(timeout=4))
            cancel_thread.start()
            self.assertTrue(cancel_intent_set.wait(timeout=2))
            release_monitor.set()
            terminal = self.wait_terminal(supervisor, request.task_id, timeout=2)
            release_cancel.set()
            cancel_thread.join(timeout=4)
        finally:
            release_monitor.set()
            release_cancel.set()
            runtime.process.is_alive = original_is_alive
            supervisor._terminate = original_terminate

        self.assertFalse(cancel_thread.is_alive())
        self.assertEqual(cancel_errors, [])
        self.assertEqual(terminal.status, WorkerTaskStatus.CANCELLED)
        self.assertEqual(cancel_results[0].status, WorkerTaskStatus.CANCELLED)

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

    def test_terminal_publication_prunes_history_before_cleanup_finishes(self):
        supervisor = self.make_supervisor(worker_fixtures.succeed, max_records=2)
        retained = []
        for index in range(2):
            item = WorkerTaskRequest.new("engineer", f"retained-{index}", 10)
            supervisor.submit(item)
            self.wait_terminal(supervisor, item.task_id)
            deadline = time.monotonic() + 2
            while item.task_id in supervisor._runtimes and time.monotonic() < deadline:
                time.sleep(0.01)
            retained.append(item.task_id)

        blocked = WorkerTaskRequest.new("engineer", "blocked cleanup", 10)
        original_cleanup = supervisor._cleanup_runtime
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()

        def pause_cleanup(task_id):
            if task_id == blocked.task_id:
                cleanup_started.set()
                release_cleanup.wait(timeout=4)
            original_cleanup(task_id)

        supervisor._cleanup_runtime = pause_cleanup
        try:
            supervisor.submit(blocked)
            self.wait_terminal(supervisor, blocked.task_id)
            self.assertTrue(cleanup_started.wait(timeout=2))
            visible_ids = [record.task_id for record in supervisor.list()]
        finally:
            release_cleanup.set()
            deadline = time.monotonic() + 2
            while blocked.task_id in supervisor._runtimes and time.monotonic() < deadline:
                time.sleep(0.01)
            supervisor._cleanup_runtime = original_cleanup

        self.assertEqual(visible_ids, [blocked.task_id, retained[-1]])

    def test_concurrent_terminal_publication_bounds_history_before_cleanup(self):
        supervisor = self.make_supervisor(worker_fixtures.succeed, max_records=1)
        requests = [
            WorkerTaskRequest.new("engineer", "first terminal", 10),
            WorkerTaskRequest.new("reviewer", "second terminal", 10),
        ]
        original_cleanup = supervisor._cleanup_runtime
        cleanup_started = {
            request.task_id: threading.Event() for request in requests
        }
        release_cleanup = threading.Event()
        runtimes = {}

        def pause_cleanup(task_id):
            cleanup_started[task_id].set()
            release_cleanup.wait(timeout=4)
            original_cleanup(task_id)

        supervisor._cleanup_runtime = pause_cleanup
        try:
            for request in requests:
                supervisor.submit(request)
                runtimes[request.task_id] = supervisor._runtimes[request.task_id]
            for request in requests:
                self.assertTrue(cleanup_started[request.task_id].wait(timeout=4))
            visible_records = supervisor.list()
            active_processes = supervisor.active_process_count()
        finally:
            release_cleanup.set()
            deadline = time.monotonic() + 2
            while supervisor._runtimes and time.monotonic() < deadline:
                time.sleep(0.01)
            supervisor._cleanup_runtime = original_cleanup

        self.assertEqual(len(visible_records), 1)
        self.assertEqual(active_processes, 0)
        self.assertEqual(supervisor._runtimes, {})
        for runtime in runtimes.values():
            self.assertTrue(runtime.connection.closed)
            with self.assertRaises(ValueError):
                runtime.process.is_alive()

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

    def test_termination_intent_drains_without_accepting_late_events(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 10},
        )
        request = WorkerTaskRequest.new("engineer", "ignore late heartbeat", 10)
        submitted = supervisor.submit(request)
        runtime = supervisor._runtimes[request.task_id]
        with supervisor._lock:
            runtime.termination_intent = WorkerTaskStatus.TIMEOUT
        heartbeat = WorkerEvent.new(
            request,
            sequence=submitted.last_event_sequence + 1,
            kind=WorkerEventKind.HEARTBEAT,
            payload={},
        )

        accepted = supervisor._accept_event(request.task_id, heartbeat)

        self.assertFalse(accepted)
        self.assertEqual(supervisor.get(request.task_id), submitted)

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

    def test_cancel_serializes_termination_with_runtime_cleanup(self):
        supervisor = self.make_supervisor(
            worker_fixtures.sleep_then_succeed,
            runner_config={"delay": 30},
            termination_grace=0.5,
        )
        request = WorkerTaskRequest.new("engineer", "cancel cleanup race", 30)
        supervisor.submit(request)
        runtime = supervisor._runtimes[request.task_id]
        original_terminate = runtime.process.terminate
        original_join = runtime.process.join
        original_close = runtime.process.close
        process_closed = threading.Event()

        def terminate_then_pause():
            original_terminate()
            process_closed.wait(timeout=0.25)

        def reject_join_after_close(timeout=None):
            if process_closed.is_set():
                raise OSError(6, "invalid process handle")
            return original_join(timeout=timeout)

        def close_and_signal():
            try:
                return original_close()
            finally:
                process_closed.set()

        runtime.process.terminate = terminate_then_pause
        runtime.process.join = reject_join_after_close
        runtime.process.close = close_and_signal
        try:
            terminal = supervisor.cancel(request.task_id)
        finally:
            supervisor.shutdown()

        self.assertEqual(terminal.status, WorkerTaskStatus.CANCELLED)
        self.assertTrue(terminal.termination_confirmed)
        self.assertTrue(process_closed.wait(timeout=2))

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

    def test_fixed_role_runner_uses_direct_execution_without_transport_timeout(self):
        request = WorkerTaskRequest.new("engineer", "inspect", 17)
        manager = Mock()
        manager.get_token_usage.return_value.to_dict.return_value = {
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "total_tokens": 5,
        }
        dispatch = Mock(status="success")
        dispatch.to_dict.return_value = {
            "role_name": "engineer",
            "task_id": request.task_id,
            "status": "success",
            "message": "done",
        }
        factory = Mock()
        factory.execute_role_once.return_value = dispatch

        with (
            patch(
                "core.kernel.ollama_manager.OllamaManager",
                return_value=manager,
            ) as manager_type,
            patch(
                "core.brain.agent_factory.AgentFactory",
                return_value=factory,
            ) as factory_type,
        ):
            result = execute_role_task(
                request.to_dict(),
                {
                    "ollama_base_url": "http://fixture.local",
                    "role_model": "fixture-model",
                },
            )

        manager_type.assert_called_once_with(
            base_url="http://fixture.local",
            timeout=None,
        )
        factory_type.assert_called_once_with(
            ollama_manager=manager,
            role_model="fixture-model",
        )
        factory.execute_role_once.assert_called_once_with(
            "engineer",
            "inspect",
            task_id=request.task_id,
        )
        factory.dispatch_by_role.assert_not_called()
        factory.shutdown.assert_called_once_with()
        self.assertEqual(result["dispatch"]["task_id"], request.task_id)


if __name__ == "__main__":
    unittest.main()
