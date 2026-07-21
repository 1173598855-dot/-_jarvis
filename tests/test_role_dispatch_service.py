from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
import re
import threading
import time
import unittest

from core.brain.agent_factory import DispatchResult
from core.brain.role_dispatch_service import (
    ROLE_TASK_TERMINATION_UNCONFIRMED,
    ROLE_WORKER_INVALID_RESULT,
    ROLE_WORKER_UNAVAILABLE,
    RoleDispatchService,
    RoleTaskTerminationUnconfirmedError,
    RoleWorkerInvalidResultError,
    RoleWorkerUnavailableError,
)
from core.brain.role_registry import AgentProfile, RoleRegistry
from core.brain.role_worker import RoleWorkerSupervisor
from core.contracts.worker_protocol import (
    WorkerTaskRecord,
    WorkerTaskRequest,
    WorkerTaskStatus,
)


class _TaskIds:
    def __init__(self, *task_ids: str) -> None:
        self._task_ids = deque(task_ids)

    def __call__(self) -> str:
        return self._task_ids.popleft()


def _registry() -> RoleRegistry:
    registry = RoleRegistry()
    registry.register(
        AgentProfile(
            name="engineer",
            display_name="Engineer",
            description="Builds things",
            capabilities=["coding", "testing"],
            priority=5,
        )
    )
    registry.register(
        AgentProfile(
            name="architect",
            display_name="Architect",
            description="Designs things",
            capabilities=["coding", "design"],
            priority=9,
        )
    )
    return registry


def _record(
    request: WorkerTaskRequest,
    status: WorkerTaskStatus,
    *,
    result: object = None,
    error: str = "",
    termination_confirmed: bool = True,
) -> WorkerTaskRecord:
    return WorkerTaskRecord.from_request(request).evolve(
        status=status,
        result=result,
        error=error,
        termination_confirmed=termination_confirmed,
    )


def _success_record(
    request: WorkerTaskRequest,
    *,
    inner_task_id: str = "inner-task",
    message: str = "done",
) -> WorkerTaskRecord:
    return _record(
        request,
        WorkerTaskStatus.SUCCEEDED,
        result={
            "dispatch": {
                "role_name": request.role_name,
                "task_id": inner_task_id,
                "status": "success",
                "message": message,
            }
        },
    )


def _sleep_then_return_role_dispatch(
    request_value: Mapping[str, object],
    config: Mapping[str, object],
) -> dict[str, object]:
    time.sleep(float(config["delay"]))
    return {
        "dispatch": {
            "role_name": request_value["role_name"],
            "task_id": "inner-task",
            "status": "success",
            "message": "done",
        }
    }


class _FakeSupervisor:
    def __init__(
        self,
        result_factory: Callable[[WorkerTaskRequest], WorkerTaskRecord | None]
        | None = None,
    ) -> None:
        self.records: dict[str, WorkerTaskRecord] = {}
        self.submitted: list[WorkerTaskRequest] = []
        self.waited: list[tuple[str, float]] = []
        self.observers: list[Callable[[WorkerTaskRecord], None]] = []
        self.result_factory = result_factory or _success_record
        self.submit_hook: Callable[[WorkerTaskRequest], None] | None = None

    def add_terminal_observer(
        self,
        observer: Callable[[WorkerTaskRecord], None],
    ) -> None:
        self.observers.append(observer)

    def submit(self, request: WorkerTaskRequest) -> WorkerTaskRecord:
        if self.submit_hook is not None:
            self.submit_hook(request)
        self.submitted.append(request)
        running = WorkerTaskRecord.from_request(request).evolve(
            status=WorkerTaskStatus.RUNNING
        )
        self.records[request.task_id] = running
        return running

    def get(self, task_id: str) -> WorkerTaskRecord | None:
        return self.records.get(task_id)

    def wait(self, task_id: str, timeout: float) -> WorkerTaskRecord | None:
        self.waited.append((task_id, timeout))
        request = next(
            request for request in self.submitted if request.task_id == task_id
        )
        result = self.result_factory(request)
        if result is not None:
            self.records[task_id] = result
        return result

    @staticmethod
    def terminal_wait_budget(timeout_seconds: int) -> float:
        return timeout_seconds + 0.25

    def publish(self, record: WorkerTaskRecord) -> None:
        self.records[record.task_id] = record
        for observer in tuple(self.observers):
            observer(record)


class TestRoleDispatchServiceSelectionAndMapping(unittest.TestCase):
    def test_supervisor_property_is_read_only_and_preserves_identity(self) -> None:
        supervisor = _FakeSupervisor()
        service = RoleDispatchService(_registry(), supervisor)

        self.assertIs(service.supervisor, supervisor)
        with self.assertRaises(AttributeError):
            service.supervisor = _FakeSupervisor()

    def test_role_and_highest_priority_capability_selection(self) -> None:
        supervisor = _FakeSupervisor()
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-role", "task-capability"),
        )

        by_role = service.dispatch_by_role("engineer", "implement", timeout=17)
        by_capability = service.dispatch_by_capability(
            "coding", "design", timeout=23
        )

        self.assertEqual(by_role.to_dict(), {
            "role_name": "engineer",
            "task_id": "task-role",
            "status": "success",
            "message": "done",
        })
        self.assertEqual(by_capability.role_name, "architect")
        self.assertEqual(by_capability.task_id, "task-capability")
        self.assertEqual(
            [
                (item.role_name, item.prompt, item.timeout_seconds)
                for item in supervisor.submitted
            ],
            [
                ("engineer", "implement", 17),
                ("architect", "design", 23),
            ],
        )
        self.assertEqual(
            supervisor.waited,
            [("task-role", 17.25), ("task-capability", 23.25)],
        )

    def test_unknown_role_and_capability_do_not_submit(self) -> None:
        supervisor = _FakeSupervisor()
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-unused"),
        )

        missing_role = service.dispatch_by_role("missing", "prompt")
        missing_capability = service.dispatch_by_capability("missing", "prompt")

        self.assertEqual(
            missing_role.to_dict(),
            {
                "role_name": "missing",
                "task_id": "",
                "status": "no_role",
                "message": "Role 'missing' not found",
            },
        )
        self.assertEqual(
            missing_capability.to_dict(),
            {
                "role_name": "",
                "task_id": "",
                "status": "no_capability",
                "message": "No role with capability 'missing'",
            },
        )
        self.assertEqual(supervisor.submitted, [])

    def test_outer_worker_task_id_replaces_inner_dispatch_id(self) -> None:
        supervisor = _FakeSupervisor(
            lambda request: _success_record(
                request,
                inner_task_id="untrusted-inner-id",
                message="worker output",
            )
        )
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-public-id"),
        )

        result = service.dispatch_by_role("engineer", "prompt")

        self.assertEqual(result.task_id, "task-public-id")
        self.assertEqual(result.role_name, "engineer")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "worker output")

    def test_default_task_ids_satisfy_worker_identifier_contract(self) -> None:
        supervisor = _FakeSupervisor()
        service = RoleDispatchService(_registry(), supervisor)

        result = service.dispatch_by_role("engineer", "prompt")

        self.assertRegex(
            result.task_id,
            re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
        )
        self.assertEqual(supervisor.submitted[0].task_id, result.task_id)

    def test_success_payload_is_decoded_strictly(self) -> None:
        valid = {
            "role_name": "engineer",
            "task_id": "inner",
            "status": "success",
            "message": "done",
        }
        invalid_payloads = {
            "result is not a mapping": None,
            "dispatch is missing": {},
            "dispatch is not a mapping": {"dispatch": "invalid"},
            "extra key": {"dispatch": {**valid, "usage": {}}},
            "missing key": {
                "dispatch": {
                    key: value
                    for key, value in valid.items()
                    if key != "message"
                }
            },
            "non-string role": {"dispatch": {**valid, "role_name": 7}},
            "non-string task id": {"dispatch": {**valid, "task_id": 7}},
            "non-string status": {"dispatch": {**valid, "status": 7}},
            "non-string message": {"dispatch": {**valid, "message": 7}},
            "wrong role": {"dispatch": {**valid, "role_name": "architect"}},
        }

        for label, payload in invalid_payloads.items():
            with self.subTest(label=label):
                supervisor = _FakeSupervisor(
                    lambda request, payload=payload: _record(
                        request,
                        WorkerTaskStatus.SUCCEEDED,
                        result=payload,
                    )
                )
                service = RoleDispatchService(
                    _registry(),
                    supervisor,
                    task_id_factory=_TaskIds("task-invalid"),
                )

                with self.assertRaises(RoleWorkerInvalidResultError) as raised:
                    service.dispatch_by_role("engineer", "prompt")

                self.assertEqual(raised.exception.role_name, "engineer")
                self.assertEqual(raised.exception.task_id, "task-invalid")
                self.assertEqual(str(raised.exception), ROLE_WORKER_INVALID_RESULT)

    def test_missing_wait_record_is_an_invalid_worker_result(self) -> None:
        supervisor = _FakeSupervisor(lambda _request: None)
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-missing-record"),
        )

        with self.assertRaises(RoleWorkerInvalidResultError) as raised:
            service.dispatch_by_role("engineer", "prompt")

        self.assertEqual(raised.exception.role_name, "engineer")
        self.assertEqual(raised.exception.task_id, "task-missing-record")
        self.assertEqual(str(raised.exception), ROLE_WORKER_INVALID_RESULT)

    def test_confirmed_timeout_has_stable_public_mapping(self) -> None:
        supervisor = _FakeSupervisor(
            lambda request: _record(
                request,
                WorkerTaskStatus.TIMEOUT,
                error="Worker task timed out after 3s with secret details",
            )
        )
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-timeout"),
        )

        result = service.dispatch_by_role("engineer", "prompt", timeout=3)

        self.assertEqual(result.to_dict(), {
            "role_name": "engineer",
            "task_id": "task-timeout",
            "status": "timeout",
            "message": "Role task timed out",
        })

    def test_failed_crashed_and_cancelled_have_stable_redacted_mappings(self) -> None:
        cases = {
            WorkerTaskStatus.FAILED: "Role task failed",
            WorkerTaskStatus.CRASHED: "Role worker crashed",
            WorkerTaskStatus.CANCELLED: "Role task cancelled",
        }

        for index, (status, expected_message) in enumerate(cases.items()):
            with self.subTest(status=status):
                supervisor = _FakeSupervisor(
                    lambda request, status=status: _record(
                        request,
                        status,
                        error="Bearer secret-value",
                    )
                )
                service = RoleDispatchService(
                    _registry(),
                    supervisor,
                    task_id_factory=_TaskIds(f"task-terminal-{index}"),
                )

                result = service.dispatch_by_role("engineer", "prompt")

                self.assertEqual(result.status, "error")
                self.assertEqual(result.message, expected_message)
                self.assertNotIn("secret-value", result.message)


class TestRoleDispatchServiceLeases(unittest.TestCase):
    def test_nonterminal_and_unconfirmed_terminal_records_retain_the_lease(
        self,
    ) -> None:
        cases = (
            (WorkerTaskStatus.RUNNING, False),
            (WorkerTaskStatus.FAILED, False),
        )
        for index, (status, confirmed) in enumerate(cases):
            with self.subTest(status=status):
                supervisor = _FakeSupervisor(
                    lambda request, status=status, confirmed=confirmed: _record(
                        request,
                        status,
                        termination_confirmed=confirmed,
                    )
                )
                first_id = f"task-retained-{index}"
                second_id = f"task-busy-{index}"
                service = RoleDispatchService(
                    _registry(),
                    supervisor,
                    task_id_factory=_TaskIds(first_id, second_id),
                )

                with self.assertRaises(RoleTaskTerminationUnconfirmedError) as raised:
                    service.dispatch_by_role("engineer", "first")
                busy = service.dispatch_by_role("engineer", "second")

                self.assertEqual(raised.exception.role_name, "engineer")
                self.assertEqual(raised.exception.task_id, first_id)
                self.assertEqual(
                    str(raised.exception), ROLE_TASK_TERMINATION_UNCONFIRMED
                )
                self.assertEqual(busy.to_dict(), {
                    "role_name": "engineer",
                    "task_id": second_id,
                    "status": "busy",
                    "message": "Agent 'engineer' is busy",
                })
                self.assertEqual(len(supervisor.submitted), 1)
                self.assertNotIn(second_id, supervisor.records)

    def test_terminal_observer_releases_lease_for_same_role_reuse(self) -> None:
        supervisor = _FakeSupervisor(
            lambda request: _record(
                request,
                WorkerTaskStatus.RUNNING,
                termination_confirmed=False,
            )
        )
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-first", "task-second"),
        )

        with self.assertRaises(RoleTaskTerminationUnconfirmedError):
            service.dispatch_by_role("engineer", "first")
        first_request = supervisor.submitted[0]
        supervisor.publish(_success_record(first_request))
        supervisor.result_factory = _success_record

        second = service.dispatch_by_role("engineer", "second")

        self.assertEqual(second.task_id, "task-second")
        self.assertEqual(second.status, "success")
        self.assertEqual(len(supervisor.submitted), 2)

    def test_submit_failure_without_record_rolls_back_reservation(self) -> None:
        supervisor = _FakeSupervisor()
        attempts = 0

        def fail_once_before_record(_request: WorkerTaskRequest) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("spawn failed with local detail")

        supervisor.submit_hook = fail_once_before_record
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-failed", "task-retry"),
        )

        with self.assertRaises(RoleWorkerUnavailableError) as raised:
            service.dispatch_by_role("engineer", "first")
        retried = service.dispatch_by_role("engineer", "second")

        self.assertEqual(raised.exception.role_name, "engineer")
        self.assertEqual(raised.exception.task_id, "task-failed")
        self.assertEqual(str(raised.exception), ROLE_WORKER_UNAVAILABLE)
        self.assertEqual(retried.task_id, "task-retry")
        self.assertEqual(retried.status, "success")

    def test_submit_failure_with_established_record_retains_lease(self) -> None:
        supervisor = _FakeSupervisor()

        def establish_record_then_fail(request: WorkerTaskRequest) -> None:
            supervisor.records[request.task_id] = WorkerTaskRecord.from_request(
                request
            ).evolve(status=WorkerTaskStatus.RUNNING)
            raise OSError("submit returned after partial start")

        supervisor.submit_hook = establish_record_then_fail
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-partial", "task-busy"),
        )

        with self.assertRaises(RoleWorkerUnavailableError):
            service.dispatch_by_role("engineer", "first")
        busy = service.dispatch_by_role("engineer", "second")

        self.assertEqual(busy.status, "busy")
        self.assertEqual(busy.task_id, "task-busy")
        self.assertIn("task-partial", supervisor.records)

    def test_missing_pruned_terminal_lease_becomes_reusable(self) -> None:
        supervisor = _FakeSupervisor(
            lambda request: _record(
                request,
                WorkerTaskStatus.RUNNING,
                termination_confirmed=False,
            )
        )
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-pruned", "task-reused"),
        )

        with self.assertRaises(RoleTaskTerminationUnconfirmedError):
            service.dispatch_by_role("engineer", "first")
        supervisor.records.pop("task-pruned")
        supervisor.result_factory = _success_record

        reused = service.dispatch_by_role("engineer", "second")

        self.assertEqual(reused.task_id, "task-reused")
        self.assertEqual(reused.status, "success")
        self.assertEqual(len(supervisor.submitted), 2)

    def test_pending_reservation_cannot_be_stolen_before_submit(self) -> None:
        supervisor = _FakeSupervisor()
        submit_entered = threading.Event()
        release_submit = threading.Event()
        first_results: list[DispatchResult] = []
        first_errors: list[BaseException] = []

        def pause_before_submit(_request: WorkerTaskRequest) -> None:
            submit_entered.set()
            release_submit.wait(timeout=4)

        supervisor.submit_hook = pause_before_submit
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-first", "task-second"),
        )

        def dispatch_first() -> None:
            try:
                first_results.append(
                    service.dispatch_by_role("engineer", "first")
                )
            except BaseException as exc:
                first_errors.append(exc)

        first_thread = threading.Thread(target=dispatch_first, daemon=True)
        first_thread.start()
        try:
            self.assertTrue(submit_entered.wait(timeout=2))
            second = service.dispatch_by_role("engineer", "second")
        finally:
            release_submit.set()
            first_thread.join(timeout=4)

        self.assertFalse(first_thread.is_alive())
        self.assertEqual(first_errors, [])
        self.assertEqual(first_results[0].task_id, "task-first")
        self.assertEqual(second.status, "busy")
        self.assertEqual(second.task_id, "task-second")
        self.assertEqual(len(supervisor.submitted), 1)


class TestRoleDispatchServiceLockOrder(unittest.TestCase):
    def test_supervisor_apis_stay_responsive_while_observer_waits_for_lease_lock(
        self,
    ) -> None:
        terminal_published = threading.Event()
        release_submit = threading.Event()
        submit_returned = threading.Event()
        supervisor = RoleWorkerSupervisor(
            _sleep_then_return_role_dispatch,
            runner_config={"delay": 0.15},
            heartbeat_interval=0.02,
            termination_grace=0.1,
            on_terminal=lambda _record: terminal_published.set(),
        )
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds("task-race-first", "task-race-second"),
        )
        original_submit = supervisor.submit
        first_results: list[DispatchResult] = []
        first_errors: list[BaseException] = []

        def pause_submit(request: WorkerTaskRequest) -> WorkerTaskRecord:
            submitted = original_submit(request)
            submit_returned.set()
            release_submit.wait(timeout=4)
            return submitted

        supervisor.submit = pause_submit

        def dispatch_first() -> None:
            try:
                first_results.append(
                    service.dispatch_by_role("engineer", "first", timeout=2)
                )
            except BaseException as exc:
                first_errors.append(exc)

        first_thread = threading.Thread(target=dispatch_first, daemon=True)
        first_thread.start()
        lock_acquired = False
        try:
            self.assertTrue(submit_returned.wait(timeout=2))
            service._lease_lock.acquire()
            lock_acquired = True
            release_submit.set()
            self.assertTrue(terminal_published.wait(timeout=4))

            outcomes: dict[str, object] = {}
            completed = {
                "get": threading.Event(),
                "list": threading.Event(),
                "wait": threading.Event(),
            }

            def call_api(name: str, operation: Callable[[], object]) -> None:
                outcomes[name] = operation()
                completed[name].set()

            api_threads = [
                threading.Thread(
                    target=call_api,
                    args=("get", lambda: supervisor.get("task-race-first")),
                    daemon=True,
                ),
                threading.Thread(
                    target=call_api,
                    args=("list", supervisor.list),
                    daemon=True,
                ),
                threading.Thread(
                    target=call_api,
                    args=("wait", lambda: supervisor.wait("task-race-first", 1)),
                    daemon=True,
                ),
            ]
            for thread in api_threads:
                thread.start()
            for name, event in completed.items():
                self.assertTrue(event.wait(timeout=1), f"{name} remained blocked")
            for thread in api_threads:
                thread.join(timeout=1)

            self.assertTrue(outcomes["get"].status.is_terminal)
            self.assertEqual(outcomes["wait"], outcomes["get"])
            self.assertEqual(outcomes["list"][0], outcomes["get"])
        finally:
            release_submit.set()
            if lock_acquired:
                service._lease_lock.release()

        try:
            first_thread.join(timeout=4)
            self.assertFalse(first_thread.is_alive())
            self.assertEqual(first_errors, [])
            self.assertEqual(first_results[0].status, "success")

            deadline = time.monotonic() + 3
            while (
                "task-race-first" in supervisor._runtimes
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertNotIn("task-race-first", supervisor._runtimes)
            self.assertNotIn("engineer", service._leases)

            supervisor.submit = original_submit
            second = service.dispatch_by_role("engineer", "second", timeout=2)
            self.assertEqual(second.task_id, "task-race-second")
            self.assertEqual(second.status, "success")
        finally:
            supervisor.submit = original_submit
            supervisor.shutdown()
            self.assertEqual(supervisor.active_process_count(), 0)


class TestRoleDispatchServiceBatch(unittest.TestCase):
    def test_batch_preserves_full_ordered_compatibility_matrix(self) -> None:
        supervisor = _FakeSupervisor()
        service = RoleDispatchService(
            _registry(),
            supervisor,
            task_id_factory=_TaskIds(
                "task-invalid-blank",
                "task-invalid-timeout",
                "task-invalid-mapping",
                "task-invalid-route",
            ),
        )
        calls: list[tuple[str, str, str, int]] = []

        def by_role(role: str, prompt: str, timeout: int = 300) -> DispatchResult:
            calls.append(("role", role, prompt, timeout))
            if prompt == "infrastructure failure":
                raise RoleWorkerUnavailableError(
                    role,
                    "task-infrastructure",
                    ROLE_WORKER_UNAVAILABLE,
                )
            status = "no_role" if role == "missing" else "success"
            return DispatchResult(role, f"call-{len(calls)}", status, prompt)

        def by_capability(
            capability: str,
            prompt: str,
            timeout: int = 300,
        ) -> DispatchResult:
            calls.append(("capability", capability, prompt, timeout))
            return DispatchResult(
                "architect", f"call-{len(calls)}", "success", prompt
            )

        service.dispatch_by_role = by_role
        service.dispatch_by_capability = by_capability
        tasks = [
            {"role": "engineer", "prompt": "role", "timeout": 10},
            {"capability": "coding", "prompt": "capability", "timeout": 11},
            {"prompt": "default route"},
            {"role": "missing", "prompt": "unknown route"},
            {"role": "engineer", "prompt": "   "},
            {"role": "engineer", "prompt": "invalid timeout", "timeout": True},
            "not a mapping",
            {"role": 7, "capability": "coding", "prompt": "invalid route"},
            {
                "role": "engineer",
                "prompt": "extra fields",
                "unknown": {"nested": "ignored"},
            },
            {"role": "engineer", "prompt": "infrastructure failure"},
        ]

        results = service.batch_dispatch(tasks)

        self.assertEqual(len(results), len(tasks))
        self.assertEqual(
            [(result.status, result.message) for result in results],
            [
                ("success", "role"),
                ("success", "capability"),
                ("success", "default route"),
                ("no_role", "unknown route"),
                ("error", "Invalid batch dispatch item"),
                ("error", "Invalid batch dispatch item"),
                ("error", "Invalid batch dispatch item"),
                ("error", "Invalid batch dispatch item"),
                ("success", "extra fields"),
                ("error", ROLE_WORKER_UNAVAILABLE),
            ],
        )
        self.assertEqual(
            calls,
            [
                ("role", "engineer", "role", 10),
                ("capability", "coding", "capability", 11),
                ("role", "architect", "default route", 300),
                ("role", "missing", "unknown route", 300),
                ("role", "engineer", "extra fields", 300),
                ("role", "engineer", "infrastructure failure", 300),
            ],
        )
        self.assertEqual(
            [result.task_id for result in results[4:8]],
            [
                "task-invalid-blank",
                "task-invalid-timeout",
                "task-invalid-mapping",
                "task-invalid-route",
            ],
        )
        self.assertEqual(results[-1].task_id, "task-infrastructure")


if __name__ == "__main__":
    unittest.main()
