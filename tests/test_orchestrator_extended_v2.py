"""Extended tests v2 for orchestrator.py - Iteration 57"""
import os
import sys
import threading
import time
import unittest
import warnings
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.brain.orchestrator import (
    AgentResult,
    AgentStatus,
    AgentTask,
    Orchestrator,
    _RegisteredAgent,
)
from core.brain.orchestrator_worker import (
    MAX_DECLARED_INTEGER_DIGITS,
    MAX_DECLARED_TASK_BYTES,
    DeclaredAgentTaskError,
    DeclaredAgentWorker,
    _encode_task,
    _normalize_json_value,
    execute_declared_agent_task,
)
from core.contracts.worker_protocol import WorkerTaskRequest
from tests import orchestrator_worker_fixtures


class TestOrchestratorDispatchEdgeCases(unittest.TestCase):
    def test_dispatch_unknown_agent_returns_error_status(self):
        orch = Orchestrator()
        task = AgentTask(agent_name="nonexistent_agent_xyz", prompt="do it")
        result = orch.dispatch(task)
        self.assertEqual(result.status, "error")
        self.assertIn("not found", result.error)

    def test_dispatch_returns_duration_ms(self):
        orch = Orchestrator()
        orch.register_in_process("a", lambda t: "ok")
        task = AgentTask(agent_name="a", prompt="p")
        result = orch.dispatch(task)
        self.assertIsNotNone(result.duration_ms)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_dispatch_handler_returns_none(self):
        orch = Orchestrator()
        orch.register_in_process("a", lambda t: None)
        result = orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        self.assertEqual(result.status, "success")

    def test_dispatch_increments_stats_on_error(self):
        orch = Orchestrator()
        orch.dispatch(AgentTask(agent_name="no_such", prompt="p"))
        stats = orch.get_stats()
        self.assertEqual(stats["total_errors"], 1)
        self.assertEqual(stats["total_dispatched"], 1)

    def test_dispatch_chaining_register(self):
        orch = Orchestrator()
        result = orch.register_in_process("a", lambda t: "ok").register_in_process("b", lambda t: "ok2")
        self.assertIs(result, orch)


class TestOrchestratorCollectTaskId(unittest.TestCase):
    def test_collect_by_task_id_returns_one(self):
        orch = Orchestrator()
        orch.register_in_process("a", lambda t: "ok")
        task = AgentTask(agent_name="a", prompt="p", task_id="tid_42")
        orch.dispatch(task)
        results = orch.collect(task_id="tid_42")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_id, "tid_42")

    def test_collect_nonexistent_task_id_returns_empty(self):
        orch = Orchestrator()
        orch.register_in_process("a", lambda t: "ok")
        orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        results = orch.collect(task_id="does_not_exist_999")
        self.assertEqual(results, [])

    def test_collect_multiple_filters_together(self):
        orch = Orchestrator()
        def ok(task):
            return "ok"
        def fail(task):
            raise RuntimeError("err")
        orch.register_in_process("agent1", ok)
        orch.register_in_process("agent2", fail)
        t1 = AgentTask(agent_name="agent1", prompt="p", task_id="t1")
        t2 = AgentTask(agent_name="agent2", prompt="p", task_id="t2")
        orch.dispatch(t1)
        orch.dispatch(t2)
        # filter by agent_name AND status
        results = orch.collect(agent_name="agent1", status="success")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].agent_name, "agent1")


class TestOrchestratorHistoryOwnership(unittest.TestCase):
    def test_history_retains_only_the_newest_thousand_results(self):
        orch = Orchestrator()
        for index in range(1005):
            orch._record(
                AgentResult(
                    task_id=f"task-{index}",
                    agent_name="worker",
                    status="success",
                )
            )

        history = orch.collect(limit=5000)

        self.assertEqual(len(history), 1000)
        self.assertEqual(history[0].task_id, "task-1004")
        self.assertEqual(history[-1].task_id, "task-5")

    def test_collect_requires_an_exact_non_negative_integer_limit(self):
        orch = Orchestrator()
        orch._record(AgentResult("task", "worker", status="success"))

        self.assertEqual(orch.collect(limit=0), [])
        for invalid_limit in (-1, True, 1.0, "1"):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesRegex(
                    ValueError,
                    "limit must be a non-negative integer",
                ):
                    orch.collect(limit=invalid_limit)

    def test_collect_filters_before_applying_the_result_limit(self):
        orch = Orchestrator()
        for task_id, agent_name in (
            ("target-0", "target"),
            ("other-0", "other"),
            ("target-1", "target"),
            ("other-1", "other"),
            ("target-2", "target"),
        ):
            orch._record(
                AgentResult(task_id, agent_name, status="success")
            )

        history = orch.collect(agent_name="target", limit=2)

        self.assertEqual(
            [result.task_id for result in history],
            ["target-2", "target-1"],
        )

    def test_history_owns_recorded_and_returned_nested_results(self):
        orch = Orchestrator()
        source = AgentResult(
            "task",
            "worker",
            result={"items": ["original"]},
            status="success",
        )
        orch._record(source)

        source.status = "tampered"
        source.result["items"].append("source-change")
        first = orch.collect(limit=1)[0]

        self.assertEqual(first.status, "success")
        self.assertEqual(first.result, {"items": ["original"]})

        first.status = "changed-snapshot"
        first.result["items"].append("snapshot-change")
        second = orch.collect(limit=1)[0]

        self.assertEqual(second.status, "success")
        self.assertEqual(second.result, {"items": ["original"]})


class TestOrchestratorStats(unittest.TestCase):
    def test_stats_start_at_zero(self):
        orch = Orchestrator()
        s = orch.get_stats()
        self.assertEqual(s["total_dispatched"], 0)
        self.assertEqual(s["total_success"], 0)
        self.assertEqual(s["total_errors"], 0)
        self.assertEqual(s["total_timeouts"], 0)

    def test_stats_total_success_increments(self):
        orch = Orchestrator()
        orch.register_in_process("a", lambda t: "ok")
        orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        s = orch.get_stats()
        self.assertEqual(s["total_success"], 1)

    def test_stats_are_independent_per_orchestrator(self):
        orch1 = Orchestrator()
        orch2 = Orchestrator()
        orch1.register_in_process("a", lambda t: "ok")
        orch1.dispatch(AgentTask(agent_name="a", prompt="p"))
        s2 = orch2.get_stats()
        self.assertEqual(s2["total_dispatched"], 0)


class TestOrchestratorShutdown(unittest.TestCase):
    def test_shutdown_returns_error_for_new_dispatches(self):
        orch = Orchestrator()
        orch.shutdown()
        result = orch.dispatch(AgentTask(agent_name="a", prompt="p"))
        self.assertEqual(result.status, "error")
        self.assertIn("shutting down", result.error)

    def test_unregister_busy_agent_returns_false(self):
        orch = Orchestrator()
        def slow(task):
            time.sleep(0.1)
            return "done"
        orch.register_in_process("a", slow)
        t = AgentTask(agent_name="a", prompt="p", timeout=5)
        def do_dispatch():
            orch.dispatch(t)
        th = threading.Thread(target=do_dispatch)
        th.start()
        time.sleep(0.02)
        self.assertFalse(orch.unregister("a"))
        th.join()


class TestOrchestratorTimeoutQuarantine(unittest.TestCase):
    def _wait_for_agent_idle(self, orch, name):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            agent = next(info for info in orch.list_agents() if info.name == name)
            if agent.status == "idle":
                return
            time.sleep(0.005)
        self.fail(f"Agent {name!r} did not become idle after handler exit")

    def test_timeout_quarantines_agent_until_handler_exits(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = []

        def blocking_handler(task):
            calls.append(task.task_id)
            started.set()
            try:
                release.wait(1)
                return "late"
            finally:
                finished.set()

        orch = Orchestrator()
        orch.register_in_process("worker", blocking_handler)
        try:
            first = orch.dispatch(
                AgentTask("first", "worker", "first", timeout=0.01)
            )

            self.assertEqual(first.status, "timeout")
            self.assertTrue(started.wait(1))
            self.assertFalse(orch.unregister("worker"))
            self.assertEqual(
                orch.dispatch(
                    AgentTask("second", "worker", "second", timeout=1)
                ).status,
                "busy",
            )
            self.assertEqual(calls, ["first"])
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

        self._wait_for_agent_idle(orch, "worker")
        third = orch.dispatch(AgentTask("third", "worker", "third", timeout=1))
        self.assertEqual(third.status, "success")
        self.assertEqual(calls, ["first", "third"])
        first_history = orch.collect(task_id="first")
        self.assertEqual(len(first_history), 1)
        self.assertEqual(first_history[0].status, "timeout")

    def test_retry_does_not_reuse_unconfirmed_timed_out_handler(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = []

        def blocking_handler(task):
            calls.append(task.task_id)
            started.set()
            try:
                release.wait(1)
                return "late"
            finally:
                finished.set()

        orch = Orchestrator()
        orch.register_in_process("worker", blocking_handler)
        try:
            result = orch.dispatch_with_retry(
                AgentTask("first", "worker", "first", timeout=0.01),
                max_retries=2,
                backoff_factor=0,
            )

            self.assertEqual(result.status, "timeout")
            self.assertTrue(started.wait(1))
            self.assertEqual(calls, ["first"])
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    def test_timeout_quarantine_counts_failure_once(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_handler(_task):
            started.set()
            try:
                release.wait(1)
                return "late"
            finally:
                finished.set()

        orch = Orchestrator()
        orch.register_in_process("worker", blocking_handler)
        try:
            result = orch.dispatch(
                AgentTask("first", "worker", "first", timeout=0.01)
            )

            self.assertEqual(result.status, "timeout")
            self.assertTrue(started.wait(1))
            self.assertEqual(orch.list_agents()[0].errors_count, 1)
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

        self._wait_for_agent_idle(orch, "worker")
        self.assertEqual(orch.list_agents()[0].errors_count, 1)

    def test_handler_timeout_remains_nonrecoverable(self):
        orch = Orchestrator()

        def handler_timeout(_task):
            raise TimeoutError("handler timeout")

        orch.register_in_process("worker", handler_timeout)
        result = orch.dispatch(AgentTask("first", "worker", "first", timeout=1))

        self.assertEqual(result.status, "timeout")
        self.assertFalse(orch.recover_agent("worker"))
        agent = orch.list_agents()[0]
        self.assertEqual(agent.status, "error")
        self.assertEqual(agent.errors_count, 1)

    def test_retry_does_not_reset_busy_agent(self):
        first_started = threading.Event()
        release_first = threading.Event()
        first_finished = threading.Event()
        calls = []
        first_results = []

        def handler(task):
            calls.append(task.task_id)
            if task.task_id == "first":
                first_started.set()
                try:
                    release_first.wait(1)
                    return "first complete"
                finally:
                    first_finished.set()
            return "retry complete"

        orch = Orchestrator()
        orch.register_in_process("worker", handler)
        first_thread = threading.Thread(
            target=lambda: first_results.append(
                orch.dispatch(AgentTask("first", "worker", "first", timeout=1))
            )
        )

        try:
            first_thread.start()
            self.assertTrue(first_started.wait(1))

            retry_result = orch.dispatch_with_retry(
                AgentTask("retry", "worker", "retry", timeout=1),
                max_retries=2,
                backoff_factor=0,
            )

            self.assertEqual(retry_result.status, "failed")
            self.assertEqual(calls, ["first"])
        finally:
            release_first.set()
            self.assertTrue(first_finished.wait(1))
            first_thread.join(1)

        self.assertFalse(first_thread.is_alive())
        self.assertEqual(first_results[0].status, "success")

    def test_reregister_does_not_replace_quarantined_agent(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_handler(_task):
            started.set()
            try:
                release.wait(1)
                return "late"
            finally:
                finished.set()

        orch = Orchestrator()
        orch.register_in_process("worker", blocking_handler)
        try:
            first = orch.dispatch(
                AgentTask("first", "worker", "first", timeout=0.01)
            )

            self.assertEqual(first.status, "timeout")
            self.assertTrue(started.wait(1))
            orch.register_in_process("worker", lambda _task: "replacement")
            self.assertEqual(
                orch.dispatch(
                    AgentTask("second", "worker", "second", timeout=1)
                ).status,
                "busy",
            )
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

        self._wait_for_agent_idle(orch, "worker")
        orch.register_in_process("worker", lambda _task: "replacement")
        third = orch.dispatch(AgentTask("third", "worker", "third", timeout=1))
        self.assertEqual(third.status, "success")
        self.assertEqual(third.result, "replacement")

    def test_reregister_does_not_replace_busy_agent(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        first_results = []
        calls = []

        def blocking_handler(task):
            calls.append(task.task_id)
            started.set()
            try:
                release.wait(1)
                return "first"
            finally:
                finished.set()

        orch = Orchestrator()
        orch.register_in_process("worker", blocking_handler)
        first_thread = threading.Thread(
            target=lambda: first_results.append(
                orch.dispatch(AgentTask("first", "worker", "first", timeout=1))
            )
        )

        try:
            first_thread.start()
            self.assertTrue(started.wait(1))

            orch.register_in_process("worker", lambda _task: "replacement")
            replacement = orch.dispatch(
                AgentTask("second", "worker", "second", timeout=1)
            )

            self.assertEqual(replacement.status, "busy")
            self.assertEqual(calls, ["first"])
        finally:
            release.set()
            self.assertTrue(finished.wait(1))
            first_thread.join(1)

        self.assertFalse(first_thread.is_alive())
        self.assertEqual(first_results[0].status, "success")
        self._wait_for_agent_idle(orch, "worker")
        third = orch.dispatch(AgentTask("third", "worker", "third", timeout=1))
        self.assertEqual(third.result, "first")
        self.assertEqual(calls, ["first", "third"])

    def test_unregister_cannot_race_with_dispatch_assignment(self):
        can_unregister_entered = threading.Event()
        allow_unregister = threading.Event()
        handler_started = threading.Event()
        release_handler = threading.Event()
        unregister_results = []
        dispatch_results = []

        def handler(_task):
            handler_started.set()
            release_handler.wait(1)
            return "done"

        orch = Orchestrator()
        orch.register_in_process("worker", handler)
        agent = orch._agents["worker"]
        original_can_unregister = agent.can_unregister

        def delayed_can_unregister():
            can_unregister_entered.set()
            allow_unregister.wait(1)
            return original_can_unregister()

        agent.can_unregister = delayed_can_unregister
        unregister_thread = threading.Thread(
            target=lambda: unregister_results.append(orch.unregister("worker"))
        )
        dispatch_thread = threading.Thread(
            target=lambda: dispatch_results.append(
                orch.dispatch(AgentTask("racing", "worker", "prompt", timeout=1))
            )
        )

        try:
            unregister_thread.start()
            self.assertTrue(can_unregister_entered.wait(1))
            dispatch_thread.start()
            self.assertFalse(handler_started.wait(0.05))
            allow_unregister.set()
        finally:
            allow_unregister.set()
            release_handler.set()
            unregister_thread.join(1)
            dispatch_thread.join(1)

        self.assertFalse(unregister_thread.is_alive())
        self.assertFalse(dispatch_thread.is_alive())
        self.assertEqual(unregister_results, [True])
        self.assertEqual(dispatch_results[0].status, "error")
        self.assertIn("not found", dispatch_results[0].error)

    def test_timeout_completion_preserves_shutdown_state(self):
        release = threading.Event()
        finished = threading.Event()

        def blocking_handler(_task):
            try:
                release.wait(1)
                return "late"
            finally:
                finished.set()

        orch = Orchestrator()
        orch.register_in_process("worker", blocking_handler)
        first = orch.dispatch(
            AgentTask("first", "worker", "first", timeout=0.01)
        )
        pending_thread = orch._agents["worker"]._pending_thread
        self.assertEqual(first.status, "timeout")
        self.assertIsNotNone(pending_thread)

        try:
            orch.shutdown()
        finally:
            release.set()
            self.assertTrue(finished.wait(1))
            pending_thread.join(1)

        self.assertFalse(pending_thread.is_alive())
        self.assertEqual(orch.list_agents()[0].status, "shutdown")


class TestOrchestratorDeclaredWorker(unittest.TestCase):
    def test_declared_echo_runs_in_a_child_process_with_full_task_projection(self):
        orch = Orchestrator()
        self.assertIs(
            orch.register_declared("worker", "echo", capabilities=["analysis"]),
            orch,
        )
        try:
            result = orch.dispatch(
                AgentTask(
                    task_id="caller-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    priority=3,
                    metadata={"label": "fixture"},
                )
            )
        finally:
            orch.shutdown()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.task_id, "caller-task")
        self.assertEqual(
            result.result,
            {
                "agent_name": "worker",
                "metadata": {"label": "fixture"},
                "priority": 3,
                "prompt": "inspect",
                "task_id": "caller-task",
                "timeout": 1,
                "worker_pid": result.result["worker_pid"],
            },
        )
        self.assertNotEqual(result.result["worker_pid"], os.getpid())
        agent = orch.list_agents()[0]
        self.assertEqual(agent.capabilities, ["analysis"])
        self.assertEqual(agent.tasks_completed, 1)

    def test_declared_registration_rejects_unknown_static_runner(self):
        orch = Orchestrator()

        with self.assertRaisesRegex(ValueError, "Unknown declared runner"):
            orch.register_declared("worker", "missing-runner")

        self.assertEqual(orch.list_agents(), [])

    def test_declared_registration_rejects_hostile_runner_identifiers_without_leak(self):
        class ExplodingClass:
            @property
            def __class__(self):
                raise RuntimeError("runner-class-called")

        class ExplodingHash(str):
            def __hash__(self):
                raise RuntimeError("runner-hash-called")

        class ExplodingRepr:
            def __repr__(self):
                raise RuntimeError("runner-repr-called")

        for runner_id, marker in (
            (ExplodingClass(), "runner-class-called"),
            (ExplodingHash("echo"), "runner-hash-called"),
            (ExplodingRepr(), "runner-repr-called"),
        ):
            with self.subTest(marker=marker):
                orch = Orchestrator()
                with self.assertRaisesRegex(ValueError, "Unknown declared runner") as ctx:
                    orch.register_declared("worker", runner_id)

                self.assertNotIn(marker, str(ctx.exception))
                self.assertEqual(orch.list_agents(), [])

    def test_declared_worker_rejects_hostile_agent_name_before_comparison(self):
        class ExplodingAgentName(str):
            def __ne__(self, _other):
                raise RuntimeError("agent-name-compare-called")

        worker = DeclaredAgentWorker("worker", "echo")
        try:
            with self.assertRaises(DeclaredAgentTaskError) as ctx:
                worker.dispatch(
                    task_id="hostile-agent-name-task",
                    agent_name=ExplodingAgentName("worker"),
                    prompt="inspect",
                    timeout=1,
                    priority=1,
                    metadata={},
                )
        finally:
            worker.shutdown()

        self.assertNotIn("agent-name-compare-called", str(ctx.exception))
        self.assertEqual(worker._supervisor.active_process_count(), 0)

    def test_declared_worker_rejects_non_json_metadata_without_poisoning_agent(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            invalid = orch.dispatch(
                AgentTask(
                    task_id="invalid-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={"opaque": object()},
                )
            )
            valid = orch.dispatch(
                AgentTask(
                    task_id="valid-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=5,
                )
            )
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertIn("JSON-serializable", invalid.error)
        self.assertEqual(valid.status, "success")
        agent = orch.list_agents()[0]
        self.assertEqual(agent.errors_count, 0)
        self.assertEqual(agent.tasks_completed, 1)

    def test_declared_worker_rejects_deep_metadata_before_worker_start(self):
        metadata = {}
        current = metadata
        for _ in range(10_000):
            child = {}
            current["child"] = child
            current = child

        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            invalid = orch.dispatch(
                AgentTask(
                    task_id="deep-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata=metadata,
                )
            )
            worker = orch._agents["worker"].declared_worker
            self.assertEqual(worker._supervisor.active_process_count(), 0)
            valid = orch.dispatch(
                AgentTask(
                    task_id="after-deep-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=5,
                )
            )
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertIn("JSON-serializable", invalid.error)
        self.assertEqual(valid.status, "success")

    def test_declared_worker_rejects_non_string_metadata_keys(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            invalid = orch.dispatch(
                AgentTask(
                    task_id="invalid-key-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={1: "value"},
                )
            )
            worker = orch._agents["worker"].declared_worker
            self.assertEqual(worker._supervisor.active_process_count(), 0)
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertIn("JSON-serializable", invalid.error)

    def test_declared_worker_rejects_invalid_unicode_metadata(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            invalid = orch.dispatch(
                AgentTask(
                    task_id="invalid-unicode-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={"bad": "\ud800"},
                )
            )
            worker = orch._agents["worker"].declared_worker
            self.assertEqual(worker._supervisor.active_process_count(), 0)
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertIn("JSON-serializable", invalid.error)

    def test_declared_worker_rejects_oversized_metadata_before_worker_start(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            invalid = orch.dispatch(
                AgentTask(
                    task_id="oversized-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={"payload": "x" * MAX_DECLARED_TASK_BYTES},
                )
            )
            worker = orch._agents["worker"].declared_worker
            self.assertEqual(worker._supervisor.active_process_count(), 0)
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertIn("exceeds", invalid.error)

    def test_declared_task_preflight_rejects_escaped_prompt_before_serialization(self):
        with patch(
            "core.brain.orchestrator_worker._encode_bounded_json",
            side_effect=RuntimeError("serializer-called"),
        ) as serializer:
            with self.assertRaisesRegex(DeclaredAgentTaskError, "exceeds"):
                _encode_task(
                    task_id="escaped-prompt-task",
                    agent_name="worker",
                    prompt="\x00" * MAX_DECLARED_TASK_BYTES,
                    timeout=1,
                    priority=1,
                    metadata={},
                )

        serializer.assert_not_called()

    def test_declared_task_preflight_bounds_prompt_before_blank_check(self):
        oversized_blank_prompt = " " * (MAX_DECLARED_TASK_BYTES + 1)

        with self.assertRaisesRegex(
            DeclaredAgentTaskError,
            f"prompt exceeds {MAX_DECLARED_TASK_BYTES} bytes",
        ):
            _encode_task(
                task_id="oversized-blank-prompt-task",
                agent_name="worker",
                prompt=oversized_blank_prompt,
                timeout=1,
                priority=1,
                metadata={},
            )

    def test_declared_task_preflight_rejects_custom_mapping_without_items_leak(self):
        from collections.abc import Mapping

        class ExplodingMapping(Mapping):
            def __getitem__(self, _key):
                raise KeyError(_key)

            def __iter__(self):
                return iter(())

            def __len__(self):
                return 0

            def items(self):
                raise RuntimeError("items-called")

        with self.assertRaisesRegex(DeclaredAgentTaskError, "metadata must be an object") as ctx:
            _encode_task(
                task_id="exploding-mapping-task",
                agent_name="worker",
                prompt="inspect",
                timeout=1,
                priority=1,
                metadata=ExplodingMapping(),
            )

        self.assertNotIn("items-called", str(ctx.exception))

    def test_declared_task_preflight_rejects_hostile_metadata_type_checks(self):
        class ExplodingMetadata:
            @property
            def __class__(self):
                raise RuntimeError("metadata-class-called")

        class ExplodingValue:
            @property
            def __class__(self):
                raise RuntimeError("value-class-called")

        for metadata, marker in (
            (ExplodingMetadata(), "metadata-class-called"),
            ({"value": ExplodingValue()}, "value-class-called"),
        ):
            with self.subTest(marker=marker), patch(
                "core.brain.orchestrator_worker._encode_bounded_json",
                side_effect=RuntimeError("serializer-called"),
            ) as serializer:
                with self.assertRaises(DeclaredAgentTaskError) as ctx:
                    _encode_task(
                        task_id="hostile-metadata-task",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=1,
                        priority=1,
                        metadata=metadata,
                    )

                self.assertNotIn(marker, str(ctx.exception))
                serializer.assert_not_called()

    def test_declared_worker_rejects_hostile_metadata_type_checks_without_poisoning_agent(self):
        class ExplodingMetadata:
            @property
            def __class__(self):
                raise RuntimeError("metadata-class-called")

        class ExplodingValue:
            @property
            def __class__(self):
                raise RuntimeError("value-class-called")

        for metadata, marker in (
            (ExplodingMetadata(), "metadata-class-called"),
            ({"value": ExplodingValue()}, "value-class-called"),
        ):
            with self.subTest(marker=marker):
                orch = Orchestrator()
                orch.register_declared("worker", "echo")
                try:
                    invalid = orch.dispatch(
                        AgentTask(
                            task_id="invalid-hostile-metadata-task",
                            agent_name="worker",
                            prompt="inspect",
                            timeout=1,
                            metadata=metadata,
                        )
                    )
                    worker = orch._agents["worker"].declared_worker
                    self.assertEqual(worker._supervisor.active_process_count(), 0)
                    valid = orch.dispatch(
                        AgentTask(
                            task_id="valid-after-hostile-metadata-task",
                            agent_name="worker",
                            prompt="inspect",
                            timeout=5,
                        )
                    )
                    agent = orch.list_agents()[0]
                finally:
                    orch.shutdown()

                self.assertEqual(invalid.status, "error")
                self.assertNotIn(marker, invalid.error)
                self.assertEqual(valid.status, "success")
                self.assertEqual(agent.errors_count, 0)
                self.assertEqual(agent.tasks_completed, 1)

    def test_declared_task_preflight_rejects_custom_sequences_without_iterating(self):
        class ExplodingList(list):
            def __iter__(self):
                raise RuntimeError("list-iter-called")

        class ExplodingTuple(tuple):
            def __iter__(self):
                raise RuntimeError("tuple-iter-called")

        for metadata, marker in (
            ({"value": ExplodingList(["safe"])}, "list-iter-called"),
            ({"value": ExplodingTuple(("safe",))}, "tuple-iter-called"),
        ):
            with self.subTest(marker=marker), patch(
                "core.brain.orchestrator_worker._encode_bounded_json",
                side_effect=RuntimeError("serializer-called"),
            ) as serializer:
                with self.assertRaisesRegex(DeclaredAgentTaskError, "JSON-serializable") as ctx:
                    _encode_task(
                        task_id="exploding-sequence-task",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=1,
                        priority=1,
                        metadata=metadata,
                    )

                self.assertNotIn(marker, str(ctx.exception))
                serializer.assert_not_called()

    def test_declared_task_preflight_rejects_custom_strings_without_iterating(self):
        class ExplodingString(str):
            def __iter__(self):
                raise RuntimeError("string-iter-called")

        for prompt, metadata in (
            (ExplodingString("inspect"), {}),
            ("inspect", {ExplodingString("key"): "value"}),
        ):
            with self.subTest(prompt=prompt, metadata=metadata), patch(
                "core.brain.orchestrator_worker._encode_bounded_json",
                side_effect=RuntimeError("serializer-called"),
            ) as serializer:
                with self.assertRaises(DeclaredAgentTaskError) as ctx:
                    _encode_task(
                        task_id="exploding-string-task",
                        agent_name="worker",
                        prompt=prompt,
                        timeout=1,
                        priority=1,
                        metadata=metadata,
                    )

                self.assertNotIn("string-iter-called", str(ctx.exception))
                serializer.assert_not_called()

    def test_declared_task_preflight_rejects_custom_integer_scalars_without_stringifying(self):
        class ExplodingInt(int):
            def __str__(self):
                raise RuntimeError("integer-str-called")

        for field_name, timeout, priority in (
            ("timeout", ExplodingInt(1), 1),
            ("priority", 1, ExplodingInt(1)),
        ):
            with self.subTest(field_name=field_name), patch(
                "core.brain.orchestrator_worker._encode_bounded_json",
                side_effect=RuntimeError("serializer-called"),
            ) as serializer:
                with self.assertRaises(DeclaredAgentTaskError) as ctx:
                    _encode_task(
                        task_id="exploding-integer-task",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=timeout,
                        priority=priority,
                        metadata={},
                    )

                self.assertNotIn("integer-str-called", str(ctx.exception))
                serializer.assert_not_called()

    def test_declared_worker_rejects_custom_integer_scalars_without_poisoning_agent(self):
        class ExplodingInt(int):
            def __str__(self):
                raise RuntimeError("integer-str-called")

        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            invalid = orch.dispatch(
                AgentTask(
                    task_id="invalid-integer-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=ExplodingInt(1),
                )
            )
            worker = orch._agents["worker"].declared_worker
            self.assertEqual(worker._supervisor.active_process_count(), 0)
            valid = orch.dispatch(
                AgentTask(
                    task_id="valid-after-integer-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=5,
                )
            )
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertNotIn("integer-str-called", invalid.error)
        self.assertEqual(valid.status, "success")
        agent = orch.list_agents()[0]
        self.assertEqual(agent.errors_count, 0)
        self.assertEqual(agent.tasks_completed, 1)

    def test_declared_worker_stops_normalizing_large_metadata_sequences_at_input_budget(self):
        values = [0] * (MAX_DECLARED_TASK_BYTES * 2)
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            with patch(
                "core.brain.orchestrator_worker._normalize_json_value",
                wraps=_normalize_json_value,
            ) as normalizer:
                invalid = orch.dispatch(
                    AgentTask(
                        task_id="large-sequence-task",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=1,
                        metadata={"values": values},
                    )
                )
            worker = orch._agents["worker"].declared_worker
            self.assertEqual(worker._supervisor.active_process_count(), 0)
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertGreater(normalizer.call_count, 1)
        self.assertLess(normalizer.call_count, len(values))

    def test_declared_worker_rejects_oversized_metadata_integer_before_start(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            invalid = orch.dispatch(
                AgentTask(
                    task_id="oversized-integer-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={"value": 10 ** MAX_DECLARED_INTEGER_DIGITS},
                )
            )
            worker = orch._agents["worker"].declared_worker
            self.assertEqual(worker._supervisor.active_process_count(), 0)
        finally:
            orch.shutdown()

        self.assertEqual(invalid.status, "error")
        self.assertIn("JSON-serializable", invalid.error)

    def test_declared_child_rejects_duplicate_json_keys(self):
        request = WorkerTaskRequest.new(
            "worker",
            (
                '{"task_id":"duplicate-task","agent_name":"worker",'
                '"prompt":"inspect","timeout":1,"priority":1,'
                '"metadata":{"label":"first","label":"second"}}'
            ),
            1,
        )

        with self.assertRaisesRegex(RuntimeError, "invalid"):
            execute_declared_agent_task(
                request.to_dict(),
                {"runner_id": "echo"},
            )

    def test_declared_child_rejects_non_finite_json_constants(self):
        request = WorkerTaskRequest.new(
            "worker",
            (
                '{"task_id":"nan-task","agent_name":"worker",'
                '"prompt":"inspect","timeout":1,"priority":1,'
                '"metadata":{"value":NaN}}'
            ),
            1,
        )

        with self.assertRaisesRegex(RuntimeError, "invalid"):
            execute_declared_agent_task(
                request.to_dict(),
                {"runner_id": "echo"},
            )

    def test_declared_worker_timeout_confirms_termination_before_retry(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            timed_out = orch.dispatch(
                AgentTask(
                    task_id="slow-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={"delay_ms": 1100},
                )
            )
            agent = orch._agents["worker"]
            self.assertEqual(timed_out.status, "timeout")
            self.assertFalse(agent.has_pending_execution())
            self.assertFalse(orch.recover_agent("worker"))

            retried = orch.dispatch_with_retry(
                AgentTask(
                    task_id="retry-task",
                    agent_name="worker",
                    prompt="retry",
                    timeout=5,
                ),
                max_retries=1,
                backoff_factor=0,
            )
        finally:
            orch.shutdown()

        self.assertEqual(retried.status, "success")

    def test_declared_retry_exhaustion_preserves_single_timeout_history_entry(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        try:
            result = orch.dispatch_with_retry(
                AgentTask(
                    task_id="timeout-history",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={"delay_ms": 1100},
                ),
                max_retries=0,
                backoff_factor=0,
            )
            history = orch.collect(task_id="timeout-history")
        finally:
            orch.shutdown()

        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error, "Task timed out after 1s")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, "timeout")
        self.assertEqual(history[0].error, result.error)

    def test_declared_retry_exhaustion_uses_attempt_origin_after_legacy_replacement(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        original_dispatch = orch.dispatch

        def dispatch_then_replace(task):
            result = original_dispatch(task)
            self.assertTrue(orch.unregister("worker"))
            orch.register_in_process("worker", lambda _task: "legacy")
            return result

        try:
            with patch.object(orch, "dispatch", side_effect=dispatch_then_replace):
                result = orch.dispatch_with_retry(
                    AgentTask(
                        task_id="declared-to-legacy",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=1,
                        metadata={"delay_ms": 1100},
                    ),
                    max_retries=0,
                    backoff_factor=0,
                )
            history = orch.collect(task_id="declared-to-legacy")
        finally:
            orch.shutdown()

        self.assertEqual(result.status, "timeout")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].status, "timeout")

    def test_legacy_retry_exhaustion_uses_attempt_origin_after_declared_replacement(self):
        orch = Orchestrator()

        def timeout_handler(_task):
            raise TimeoutError("legacy timeout")

        orch.register_in_process("worker", timeout_handler)
        original_dispatch = orch.dispatch

        def dispatch_then_replace(task):
            result = original_dispatch(task)
            self.assertTrue(orch.unregister("worker"))
            orch.register_declared("worker", "echo")
            return result

        try:
            with patch.object(orch, "dispatch", side_effect=dispatch_then_replace):
                result = orch.dispatch_with_retry(
                    AgentTask(
                        task_id="legacy-to-declared",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=1,
                    ),
                    max_retries=0,
                    backoff_factor=0,
                )
            history = orch.collect(task_id="legacy-to-declared")
        finally:
            orch.shutdown()

        self.assertEqual(result.status, "failed")
        self.assertIn("after 0 retries", result.error)
        self.assertEqual(len(history), 2)
        self.assertEqual(
            [entry.status for entry in history],
            ["failed", "timeout"],
        )

    def test_unconfirmed_declared_worker_blocks_reuse_and_removal(self):
        class PendingWorker:
            released = False

            def has_pending_execution(self):
                return not self.released

            def shutdown(self):
                return None

        pending_worker = PendingWorker()
        agent = _RegisteredAgent(
            "worker",
            None,
            [],
            declared_worker=pending_worker,
        )
        agent.status = AgentStatus.ERROR
        agent._pending_declared_worker = True
        orch = Orchestrator()
        orch._agents["worker"] = agent

        self.assertFalse(orch.unregister("worker"))
        self.assertEqual(
            orch.dispatch(
                AgentTask(
                    task_id="blocked-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                )
            ).status,
            "busy",
        )
        self.assertIs(orch.register_declared("worker", "echo"), orch)
        self.assertIs(orch._agents["worker"], agent)

        pending_worker.released = True
        self.assertTrue(orch.unregister("worker"))

    def test_declared_worker_transport_error_keeps_unconfirmed_worker_quarantined(self):
        class TransportFailureWorker:
            released = False

            def dispatch(self, **_kwargs):
                raise RuntimeError("worker transport failed")

            def has_pending_execution(self):
                return not self.released

            def shutdown(self):
                return None

        pending_worker = TransportFailureWorker()
        agent = _RegisteredAgent(
            "worker",
            None,
            [],
            declared_worker=pending_worker,
        )
        orch = Orchestrator()
        orch._agents["worker"] = agent

        result = orch.dispatch(
            AgentTask(
                task_id="transport-failure-task",
                agent_name="worker",
                prompt="inspect",
                timeout=1,
            )
        )

        self.assertEqual(result.status, "error")
        self.assertTrue(agent.has_pending_execution())
        self.assertFalse(orch.recover_agent("worker"))
        self.assertFalse(orch.unregister("worker"))
        self.assertIs(orch.register_declared("worker", "echo"), orch)
        self.assertIs(orch._agents["worker"], agent)

        pending_worker.released = True
        self.assertFalse(agent.has_pending_execution())
        self.assertTrue(orch.unregister("worker"))

    def test_declared_worker_post_submit_wait_failure_is_quarantined_and_reaped(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        worker = orch._agents["worker"].declared_worker
        try:
            with patch.object(
                worker._supervisor,
                "wait",
                side_effect=RuntimeError("worker transport failed"),
            ):
                result = orch.dispatch(
                    AgentTask(
                        task_id="post-submit-failure-task",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=10,
                        metadata={"delay_ms": 10_000},
                    )
                )

            agent = orch._agents["worker"]
            self.assertEqual(result.status, "error")
            self.assertIsNotNone(worker._active_task_id)
            record = worker._supervisor.get(worker._active_task_id)
            self.assertIsNotNone(record)
            self.assertIsNotNone(record.worker_pid)
            self.assertTrue(agent.has_pending_execution())
            self.assertFalse(orch.recover_agent("worker"))
            self.assertFalse(orch.unregister("worker"))
            self.assertIs(orch.register_declared("worker", "echo"), orch)
            self.assertIs(orch._agents["worker"], agent)

            orch.shutdown()

            self.assertFalse(worker.has_pending_execution())
            self.assertEqual(worker._supervisor.active_process_count(), 0)
        finally:
            orch.shutdown()

    def test_declared_worker_post_start_submit_failure_preserves_ownership(self):
        orch = Orchestrator()
        orch.register_declared("worker", "echo")
        worker = orch._agents["worker"].declared_worker
        original_submit = worker._supervisor.submit

        def submit_then_raise(request):
            original_submit(request)
            raise RuntimeError("post-start submit failure")

        try:
            with patch.object(
                worker._supervisor,
                "submit",
                side_effect=submit_then_raise,
            ):
                result = orch.dispatch(
                    AgentTask(
                        task_id="post-start-submit-failure-task",
                        agent_name="worker",
                        prompt="inspect",
                        timeout=10,
                        metadata={"delay_ms": 10_000},
                    )
                )

            agent = orch._agents["worker"]
            self.assertEqual(result.status, "error")
            self.assertIsNotNone(worker._active_task_id)
            self.assertGreater(worker._supervisor.active_process_count(), 0)
            self.assertTrue(agent.has_pending_execution())
            self.assertFalse(orch.recover_agent("worker"))
            self.assertFalse(orch.unregister("worker"))
            self.assertIs(orch.register_declared("worker", "echo"), orch)
            self.assertIs(orch._agents["worker"], agent)

            orch.shutdown()

            self.assertFalse(worker.has_pending_execution())
            self.assertEqual(worker._supervisor.active_process_count(), 0)
        finally:
            orch.shutdown()

    def test_register_warns_and_keeps_importable_callable_in_parent_process(self):
        orch = Orchestrator()
        with self.assertWarnsRegex(
            DeprecationWarning,
            r"register_worker\(\).*register_in_process\(\)",
        ):
            registered = orch.register(
                "legacy",
                orchestrator_worker_fixtures.project_task,
            )
        try:
            result = orch.dispatch(
                AgentTask(
                    task_id="legacy-task",
                    agent_name="legacy",
                    prompt="inspect",
                    timeout=1,
                )
            )
        finally:
            orch.shutdown()

        self.assertIs(registered, orch)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["pid"], os.getpid())


class TestOrchestratorImportableWorker(unittest.TestCase):
    def test_explicit_in_process_closure_returns_self_without_warning(self):
        orch = Orchestrator()

        def local_handler(task):
            return {"pid": os.getpid(), "task_id": task.task_id}

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            registered = orch.register_in_process("local", local_handler)

        try:
            result = orch.dispatch(
                AgentTask(
                    task_id="local-task",
                    agent_name="local",
                    prompt="inspect",
                    timeout=1,
                )
            )
        finally:
            orch.shutdown()

        self.assertIs(registered, orch)
        self.assertFalse(
            any(item.category is DeprecationWarning for item in caught)
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["pid"], os.getpid())
        self.assertEqual(result.result["task_id"], "local-task")

    def test_importable_function_runs_in_child_with_task_projection(self):
        orch = Orchestrator()
        orch.register_worker("worker", orchestrator_worker_fixtures.project_task)
        try:
            result = orch.dispatch(
                AgentTask(
                    task_id="importable-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    priority=2,
                    metadata={"label": "fixture"},
                )
            )
        finally:
            orch.shutdown()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result["task_id"], "importable-task")
        self.assertEqual(result.result["priority"], 2)
        self.assertNotEqual(result.result["pid"], os.getpid())

    def test_importable_function_preserves_agent_result_shape(self):
        orch = Orchestrator()
        orch.register_worker("worker", orchestrator_worker_fixtures.result_task)
        try:
            result = orch.dispatch(
                AgentTask(
                    task_id="wrapped-task",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=5,
                )
            )
        finally:
            orch.shutdown()

        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.task_id, "wrapped-task")
        self.assertEqual(result.agent_name, "worker")
        self.assertEqual(result.result, "wrapped")
        self.assertEqual(result.status, "success")

    def test_importable_registration_rejects_unreplayable_callables_before_registry_change(self):
        def nested(_task):
            return "nested"

        class CallableObject:
            def __call__(self, _task):
                return "object"

        class Bound:
            def method(self, _task):
                return "bound"

        bound = Bound()
        callables = (
            (lambda _task: "lambda", "lambda"),
            (nested, "nested"),
            (bound.method, "bound"),
            (CallableObject(), "callable object"),
        )

        for handler, label in callables:
            with self.subTest(label=label):
                orch = Orchestrator()
                with self.assertRaisesRegex(ValueError, "top-level"):
                    orch.register_worker("worker", handler)
                self.assertEqual(orch.list_agents(), [])

    def test_importable_registration_rejects_main_module_function(self):
        def fake_main_handler(_task):
            return "main"

        fake_main_handler.__module__ = "__main__"
        orch = Orchestrator()

        with self.assertRaisesRegex(ValueError, "importable"):
            orch.register_worker("worker", fake_main_handler)

        self.assertEqual(orch.list_agents(), [])

    def test_importable_timeout_confirms_termination_before_reuse(self):
        orch = Orchestrator()
        orch.register_worker("worker", orchestrator_worker_fixtures.delayed_task)
        try:
            timed_out = orch.dispatch(
                AgentTask(
                    task_id="importable-timeout",
                    agent_name="worker",
                    prompt="inspect",
                    timeout=1,
                    metadata={"delay": 2},
                )
            )
            retried = orch.dispatch_with_retry(
                AgentTask(
                    task_id="importable-after-timeout",
                    agent_name="worker",
                    prompt="retry",
                    timeout=5,
                ),
                max_retries=1,
                backoff_factor=0,
            )
        finally:
            orch.shutdown()

        self.assertEqual(timed_out.status, "timeout")
        self.assertEqual(retried.status, "success")

    def test_importable_worker_cancel_is_confirmed_and_history_is_parent_owned(self):
        orch = Orchestrator()
        orch.register_worker("worker", orchestrator_worker_fixtures.blocking_task)
        result_box = {}

        def dispatch_task():
            result_box["result"] = orch.dispatch(
                AgentTask(
                    task_id="cancel-task",
                    agent_name="worker",
                    prompt="cancel me",
                    timeout=10,
                )
            )

        dispatch_thread = threading.Thread(target=dispatch_task, daemon=True)
        dispatch_thread.start()
        worker = orch._agents["worker"].declared_worker
        deadline = time.monotonic() + 5
        while worker._active_task_id is None and time.monotonic() < deadline:
            time.sleep(0.01)

        try:
            self.assertTrue(orch.cancel("worker", "cancel-task"))
            dispatch_thread.join(timeout=5)
            status_after_cancel = orch.list_agents()[0].status
        finally:
            orch.shutdown()

        self.assertFalse(dispatch_thread.is_alive())
        self.assertEqual(result_box["result"].status, "cancelled")
        self.assertEqual(result_box["result"].error, "Worker task cancelled")
        self.assertEqual(len(orch.collect(task_id="cancel-task")), 1)
        self.assertEqual(status_after_cancel, AgentStatus.IDLE.value)
        self.assertEqual(worker._supervisor.active_process_count(), 0)

    def test_cancel_does_not_claim_legacy_callable_termination(self):
        orch = Orchestrator()
        orch.register_in_process("legacy", lambda _task: "ok")

        self.assertFalse(orch.cancel("legacy", "missing-task"))
        orch.shutdown()


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. orchestrator extended v2 - Iteration 57")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestOrchestratorDispatchEdgeCases,
        TestOrchestratorCollectTaskId,
        TestOrchestratorHistoryOwnership,
        TestOrchestratorStats,
        TestOrchestratorShutdown,
        TestOrchestratorTimeoutQuarantine,
        TestOrchestratorDeclaredWorker,
        TestOrchestratorImportableWorker,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_all_tests())
