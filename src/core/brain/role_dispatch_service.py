from __future__ import annotations

from collections.abc import Callable, Mapping
import threading
from typing import Any, Dict, List
import uuid

from core.brain.agent_factory import DispatchResult
from core.brain.role_registry import RoleRegistry
from core.brain.role_worker import RoleWorkerSupervisor
from core.contracts.worker_protocol import (
    WorkerTaskRecord,
    WorkerTaskRequest,
    WorkerTaskStatus,
)


ROLE_WORKER_UNAVAILABLE = "Role worker is unavailable"
ROLE_TASK_TERMINATION_UNCONFIRMED = (
    "Worker process termination is not confirmed"
)
ROLE_WORKER_INVALID_RESULT = "Role worker returned an invalid result"
INVALID_BATCH_DISPATCH_ITEM = "Invalid batch dispatch item"

ROLE_TASK_FAILED = "Role task failed"
ROLE_WORKER_CRASHED = "Role worker crashed"
ROLE_TASK_CANCELLED = "Role task cancelled"


class RoleDispatchServiceError(RuntimeError):
    def __init__(self, role_name: str, task_id: str, message: str) -> None:
        super().__init__(message)
        self.role_name = role_name
        self.task_id = task_id


class RoleWorkerUnavailableError(RoleDispatchServiceError):
    pass


class RoleTaskTerminationUnconfirmedError(RoleDispatchServiceError):
    pass


class RoleWorkerInvalidResultError(RoleDispatchServiceError):
    pass


class RoleDispatchService:
    def __init__(
        self,
        registry: RoleRegistry,
        supervisor: RoleWorkerSupervisor,
        *,
        task_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._registry = registry
        self._supervisor = supervisor
        self._task_id_factory = task_id_factory or (
            lambda: f"task-{uuid.uuid4().hex}"
        )
        self._leases: dict[str, str] = {}
        self._pending_submissions: set[str] = set()
        self._lease_lock = threading.Lock()
        supervisor.add_terminal_observer(self._release_terminal_lease)

    @property
    def supervisor(self) -> RoleWorkerSupervisor:
        return self._supervisor

    def dispatch_by_role(
        self,
        role_name: str,
        task_prompt: str,
        timeout: int = 300,
    ) -> DispatchResult:
        profile = self._registry.get(role_name)
        if profile is None:
            return DispatchResult(
                role_name,
                "",
                "no_role",
                f"Role '{role_name}' not found",
            )

        task_id = self._task_id_factory()
        request = WorkerTaskRequest.new(
            profile.name,
            task_prompt,
            timeout,
            task_id=task_id,
        )
        if not self._reserve(profile.name, task_id):
            return DispatchResult(
                profile.name,
                task_id,
                "busy",
                f"Agent '{profile.name}' is busy",
            )

        try:
            self._supervisor.submit(request)
        except Exception:
            record = self._supervisor.get(task_id)
            with self._lease_lock:
                self._pending_submissions.discard(task_id)
                if record is None and self._leases.get(profile.name) == task_id:
                    self._leases.pop(profile.name, None)
            raise RoleWorkerUnavailableError(
                profile.name,
                task_id,
                ROLE_WORKER_UNAVAILABLE,
            ) from None

        with self._lease_lock:
            self._pending_submissions.discard(task_id)

        record = self._supervisor.wait(
            task_id,
            self._supervisor.terminal_wait_budget(request.timeout_seconds),
        )
        return self._decode_record(profile.name, task_id, record)

    def dispatch_by_capability(
        self,
        capability: str,
        task_prompt: str,
        timeout: int = 300,
    ) -> DispatchResult:
        candidates = self._registry.list_roles(capability=capability)
        if not candidates:
            return DispatchResult(
                "",
                "",
                "no_capability",
                f"No role with capability '{capability}'",
            )
        return self.dispatch_by_role(candidates[0].name, task_prompt, timeout)

    def batch_dispatch(
        self,
        tasks: List[Dict[str, Any]],
    ) -> List[DispatchResult]:
        results: list[DispatchResult] = []
        for item in tasks:
            route = self._batch_route(item)
            if isinstance(route, DispatchResult):
                results.append(route)
                continue
            route_kind, route_value, prompt, timeout = route
            try:
                if route_kind == "role":
                    result = self.dispatch_by_role(route_value, prompt, timeout)
                else:
                    result = self.dispatch_by_capability(
                        route_value,
                        prompt,
                        timeout,
                    )
            except RoleDispatchServiceError as exc:
                result = DispatchResult(
                    exc.role_name,
                    exc.task_id,
                    "error",
                    str(exc),
                )
            results.append(result)
        return results

    def _reserve(self, role_name: str, task_id: str) -> bool:
        with self._lease_lock:
            current_task_id = self._leases.get(role_name)
            if current_task_id is not None:
                if current_task_id in self._pending_submissions:
                    return False
                current = self._supervisor.get(current_task_id)
                if current is None or (
                    current.status.is_terminal
                    and current.termination_confirmed
                ):
                    if self._leases.get(role_name) == current_task_id:
                        self._leases.pop(role_name, None)
                else:
                    return False
            self._leases[role_name] = task_id
            self._pending_submissions.add(task_id)
            return True

    def _release_terminal_lease(self, record: WorkerTaskRecord) -> None:
        if not record.status.is_terminal or not record.termination_confirmed:
            return
        with self._lease_lock:
            self._pending_submissions.discard(record.task_id)
            if self._leases.get(record.role_name) == record.task_id:
                self._leases.pop(record.role_name, None)

    @staticmethod
    def _decode_record(
        role_name: str,
        task_id: str,
        record: WorkerTaskRecord | None,
    ) -> DispatchResult:
        if record is None:
            raise RoleWorkerInvalidResultError(
                role_name,
                task_id,
                ROLE_WORKER_INVALID_RESULT,
            )
        if not record.status.is_terminal or not record.termination_confirmed:
            raise RoleTaskTerminationUnconfirmedError(
                role_name,
                task_id,
                ROLE_TASK_TERMINATION_UNCONFIRMED,
            )
        if record.status is WorkerTaskStatus.SUCCEEDED:
            return RoleDispatchService._decode_success(role_name, task_id, record)
        if record.status is WorkerTaskStatus.TIMEOUT:
            return DispatchResult(
                role_name,
                record.task_id,
                "timeout",
                "Role task timed out",
            )
        terminal_messages = {
            WorkerTaskStatus.FAILED: ROLE_TASK_FAILED,
            WorkerTaskStatus.CRASHED: ROLE_WORKER_CRASHED,
            WorkerTaskStatus.CANCELLED: ROLE_TASK_CANCELLED,
        }
        message = terminal_messages.get(record.status)
        if message is None:
            raise RoleWorkerInvalidResultError(
                role_name,
                task_id,
                ROLE_WORKER_INVALID_RESULT,
            )
        return DispatchResult(role_name, record.task_id, "error", message)

    @staticmethod
    def _decode_success(
        role_name: str,
        task_id: str,
        record: WorkerTaskRecord,
    ) -> DispatchResult:
        result = record.result
        if not isinstance(result, Mapping):
            raise RoleWorkerInvalidResultError(
                role_name,
                task_id,
                ROLE_WORKER_INVALID_RESULT,
            )
        dispatch = result.get("dispatch")
        expected = {"role_name", "task_id", "status", "message"}
        if (
            not isinstance(dispatch, Mapping)
            or set(dispatch) != expected
            or any(not isinstance(dispatch[field], str) for field in expected)
            or dispatch["role_name"] != role_name
        ):
            raise RoleWorkerInvalidResultError(
                role_name,
                task_id,
                ROLE_WORKER_INVALID_RESULT,
            )
        return DispatchResult(
            dispatch["role_name"],
            record.task_id,
            dispatch["status"],
            dispatch["message"],
        )

    def _batch_route(
        self,
        item: object,
    ) -> tuple[str, str, str, int] | DispatchResult:
        if not isinstance(item, Mapping):
            return self._invalid_batch_item("")

        role = item.get("role", "")
        capability = item.get("capability", "")
        prompt = item.get("prompt", "")
        timeout = item.get("timeout", 300)
        role_name = role if isinstance(role, str) else ""
        if (
            (role and not isinstance(role, str))
            or (not role and capability and not isinstance(capability, str))
            or not isinstance(prompt, str)
            or not prompt.strip()
            or not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= 300
        ):
            return self._invalid_batch_item(role_name)

        if role:
            return "role", role, prompt, timeout
        if capability:
            return "capability", capability, prompt, timeout
        roles = self._registry.list_roles()
        if not roles:
            return self._invalid_batch_item("")
        return "role", roles[0].name, prompt, timeout

    def _invalid_batch_item(self, role_name: str) -> DispatchResult:
        return DispatchResult(
            role_name,
            self._task_id_factory(),
            "error",
            INVALID_BATCH_DISPATCH_ITEM,
        )
