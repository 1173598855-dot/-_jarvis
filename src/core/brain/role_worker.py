from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import multiprocessing
from multiprocessing.connection import Connection
import threading
import time
from typing import Any

from core.contracts.worker_protocol import (
    WorkerEvent,
    WorkerEventKind,
    WorkerTaskRecord,
    WorkerTaskRequest,
    WorkerTaskStatus,
)
from core.kernel.secret_redaction import redact_text


DEFAULT_MAX_RECORDS = 100
DEFAULT_MAX_OUTPUT_BYTES = 1_048_576


class WorkerTaskTerminalError(RuntimeError):
    def __init__(self, record: WorkerTaskRecord):
        super().__init__(f"worker task {record.task_id} is already terminal")
        self.record = record


class _WorkerOutputLimitError(RuntimeError):
    pass


def execute_role_task(
    request_value: Mapping[str, Any],
    trusted_config: Mapping[str, Any],
) -> dict[str, Any]:
    from core.brain.agent_factory import AgentFactory
    from core.kernel.ollama_manager import OllamaManager

    request = WorkerTaskRequest.from_dict(request_value)
    base_url = trusted_config.get("ollama_base_url")
    role_model = trusted_config.get("role_model")
    if not isinstance(base_url, str) or not base_url.strip():
        raise RuntimeError("trusted Ollama base URL is not configured")
    if not isinstance(role_model, str) or not role_model.strip():
        raise RuntimeError("trusted role model is not configured")

    manager = OllamaManager(
        base_url=base_url,
        timeout=request.timeout_seconds,
    )
    factory = AgentFactory(
        ollama_manager=manager,
        role_model=role_model,
    )
    try:
        dispatch = factory.dispatch_by_role(
            request.role_name,
            request.prompt,
            request.timeout_seconds,
        )
        if dispatch.status not in {"success", "completed", "dispatched"}:
            raise RuntimeError(dispatch.message or "Role worker execution failed")
        return {
            "dispatch": dispatch.to_dict(),
            "usage": manager.get_token_usage().to_dict(),
        }
    finally:
        factory.shutdown()


def apply_worker_token_usage(record: WorkerTaskRecord, ollama_manager: object) -> bool:
    if record.status is not WorkerTaskStatus.SUCCEEDED:
        return False
    if not isinstance(record.result, Mapping):
        return False
    usage = record.result.get("usage")
    if not isinstance(usage, Mapping):
        return False
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    if (
        not isinstance(prompt_tokens, int)
        or isinstance(prompt_tokens, bool)
        or prompt_tokens < 0
        or not isinstance(completion_tokens, int)
        or isinstance(completion_tokens, bool)
        or completion_tokens < 0
    ):
        return False
    recorder = getattr(ollama_manager, "record_token_usage", None)
    if not callable(recorder):
        return False
    recorder(prompt_tokens, completion_tokens)
    return True


@dataclass(slots=True)
class _TaskRuntime:
    request: WorkerTaskRequest
    process: multiprocessing.Process
    connection: Connection
    deadline: float
    monitor: threading.Thread | None = None
    pending_event: WorkerEvent | None = None
    termination_intent: WorkerTaskStatus | None = None
    process_lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
    )


def _bounded_json_value(value: object, max_output_bytes: int) -> object:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    if len(encoded) > max_output_bytes:
        raise _WorkerOutputLimitError(
            f"worker output limit exceeded ({max_output_bytes} bytes)"
        )
    return json.loads(encoded.decode("utf-8"))


def _worker_process_entry(
    request_value: Mapping[str, Any],
    runner: Callable[[Mapping[str, Any], Mapping[str, Any]], object],
    runner_config: Mapping[str, Any],
    connection: Connection,
    heartbeat_interval: float,
    max_output_bytes: int,
) -> None:
    request = WorkerTaskRequest.from_dict(request_value)
    sequence = 0
    send_lock = threading.Lock()
    stop_heartbeat = threading.Event()

    def send(kind: WorkerEventKind, payload: Mapping[str, Any]) -> None:
        nonlocal sequence
        with send_lock:
            sequence += 1
            event = WorkerEvent.new(
                request,
                sequence=sequence,
                kind=kind,
                payload=payload,
            )
            connection.send_bytes(
                json.dumps(
                    event.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )

    def heartbeat() -> None:
        while not stop_heartbeat.wait(heartbeat_interval):
            try:
                send(WorkerEventKind.HEARTBEAT, {})
            except (BrokenPipeError, EOFError, OSError):
                return

    try:
        send(WorkerEventKind.STARTED, {})
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        try:
            result = runner(request.to_dict(), dict(runner_config))
            normalized = _bounded_json_value(result, max_output_bytes)
        except BaseException as exc:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=heartbeat_interval * 2)
            message = redact_text(str(exc) or exc.__class__.__name__)
            if len(message.encode("utf-8")) > max_output_bytes:
                message = "worker failure exceeded the output limit"
            send(WorkerEventKind.FAILURE, {"error": message})
        else:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=heartbeat_interval * 2)
            send(WorkerEventKind.RESULT, {"result": normalized})
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        stop_heartbeat.set()
        connection.close()


class RoleWorkerSupervisor:
    def __init__(
        self,
        runner: Callable[[Mapping[str, Any], Mapping[str, Any]], object],
        *,
        runner_config: Mapping[str, Any] | None = None,
        max_records: int = DEFAULT_MAX_RECORDS,
        heartbeat_interval: float = 0.25,
        termination_grace: float = 1.0,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        on_terminal: Callable[[WorkerTaskRecord], None] | None = None,
        mp_context: multiprocessing.context.BaseContext | None = None,
    ) -> None:
        if not callable(runner):
            raise TypeError("runner must be callable")
        if not isinstance(max_records, int) or isinstance(max_records, bool) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        if termination_grace <= 0:
            raise ValueError("termination_grace must be positive")
        if (
            not isinstance(max_output_bytes, int)
            or isinstance(max_output_bytes, bool)
            or max_output_bytes < 1
        ):
            raise ValueError("max_output_bytes must be a positive integer")
        self._runner = runner
        self._runner_config = dict(runner_config or {})
        self._max_records = max_records
        self._heartbeat_interval = float(heartbeat_interval)
        self._termination_grace = float(termination_grace)
        self._max_output_bytes = max_output_bytes
        self._on_terminal = on_terminal
        self._context = mp_context or multiprocessing.get_context("spawn")
        self._records: OrderedDict[str, WorkerTaskRecord] = OrderedDict()
        self._runtimes: dict[str, _TaskRuntime] = {}
        self._lock = threading.RLock()
        self._shutdown = False

    def submit(self, request: WorkerTaskRequest) -> WorkerTaskRecord:
        if not isinstance(request, WorkerTaskRequest):
            raise TypeError("request must be a WorkerTaskRequest")
        with self._lock:
            if self._shutdown:
                raise RuntimeError("role worker supervisor is shut down")
            if request.task_id in self._records:
                raise ValueError(f"duplicate worker task_id: {request.task_id}")
            for task_id, runtime in self._runtimes.items():
                if runtime.request.role_name != request.role_name:
                    continue
                record = self._records.get(task_id)
                if record is None:
                    raise RuntimeError(
                        f"role worker termination is unconfirmed: {request.role_name}"
                    )
                if runtime.termination_intent is None:
                    continue
                if record.status.is_terminal and record.termination_confirmed:
                    continue
                raise RuntimeError(
                    f"role worker termination is unconfirmed: {request.role_name}"
                )
            receiver, sender = self._context.Pipe(duplex=False)
            process = self._context.Process(
                target=_worker_process_entry,
                args=(
                    request.to_dict(),
                    self._runner,
                    self._runner_config,
                    sender,
                    self._heartbeat_interval,
                    self._max_output_bytes,
                ),
                name=f"jarvis-role-{request.task_id[-12:]}",
            )
            record = WorkerTaskRecord.from_request(request)
            self._records[request.task_id] = record
            try:
                process.start()
            except BaseException:
                receiver.close()
                sender.close()
                self._records.pop(request.task_id, None)
                raise
            finally:
                sender.close()
            runtime = _TaskRuntime(
                request=request,
                process=process,
                connection=receiver,
                deadline=time.monotonic() + request.timeout_seconds,
            )
            running = record.evolve(
                status=WorkerTaskStatus.RUNNING,
                worker_pid=process.pid,
            )
            self._records[request.task_id] = running
            self._runtimes[request.task_id] = runtime
            monitor = threading.Thread(
                target=self._monitor,
                args=(request.task_id,),
                name=f"jarvis-role-monitor-{request.task_id[-8:]}",
                daemon=True,
            )
            runtime.monitor = monitor
            monitor.start()
            return running

    def get(self, task_id: str) -> WorkerTaskRecord | None:
        with self._lock:
            return self._records.get(task_id)

    def list(self, limit: int = 100) -> list[WorkerTaskRecord]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 through 100")
        with self._lock:
            bounded_limit = min(limit, self._max_records)
            return list(reversed(tuple(self._records.values())[-bounded_limit:]))

    def cancel(self, task_id: str) -> WorkerTaskRecord | None:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return None
            if record.status.is_terminal:
                raise WorkerTaskTerminalError(record)
            runtime = self._runtimes.get(task_id)
            if runtime is None:
                return record
            intent = runtime.termination_intent or WorkerTaskStatus.CANCELLED
            runtime.termination_intent = intent
        confirmed = self._terminate(runtime)
        if confirmed:
            error = (
                "Worker task cancelled"
                if intent is WorkerTaskStatus.CANCELLED
                else (
                    "Worker task timed out after "
                    f"{runtime.request.timeout_seconds}s"
                )
            )
            self._finalize(
                task_id,
                intent,
                error=error,
                termination_confirmed=True,
            )
        else:
            error = (
                "Worker cancellation could not confirm process termination"
                if intent is WorkerTaskStatus.CANCELLED
                else "Worker timeout could not confirm process termination"
            )
            self._update_nonterminal_error(
                task_id,
                error,
            )
        return self.get(task_id)

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown and not self._runtimes:
                return
            self._shutdown = True
            runtime_ids = list(self._runtimes)
            monitors = [
                runtime.monitor
                for runtime in self._runtimes.values()
                if runtime.monitor is not None
            ]
        for task_id in runtime_ids:
            with self._lock:
                runtime = self._runtimes.get(task_id)
                record = self._records.get(task_id)
                if runtime is None:
                    continue
                if record is None:
                    runtime.termination_intent = (
                        runtime.termination_intent or WorkerTaskStatus.CANCELLED
                    )
                elif record.status.is_terminal:
                    continue
            if record is None:
                if self._terminate(runtime):
                    self._cleanup_runtime(task_id)
                continue
            try:
                self.cancel(task_id)
            except WorkerTaskTerminalError:
                pass
        for monitor in monitors:
            if monitor is not threading.current_thread():
                monitor.join(timeout=self._termination_grace * 3)

    def active_process_count(self) -> int:
        with self._lock:
            runtimes = tuple(self._runtimes.values())
        return sum(1 for runtime in runtimes if self._process_is_alive(runtime))

    def _monitor(self, task_id: str) -> None:
        try:
            while True:
                with self._lock:
                    runtime = self._runtimes.get(task_id)
                    record = self._records.get(task_id)
                    if runtime is None:
                        return
                    if record is None:
                        record_missing = True
                    else:
                        record_missing = False
                        if record.status.is_terminal:
                            return
                        intent = runtime.termination_intent
                        pending = runtime.pending_event
                if record_missing:
                    if not self._process_is_alive(runtime):
                        return
                    time.sleep(0.01)
                    continue
                if intent in {
                    WorkerTaskStatus.CANCELLED,
                    WorkerTaskStatus.TIMEOUT,
                }:
                    if self._connection_ready(runtime.connection, 0.01):
                        self._receive_event(task_id, runtime)
                    if not self._process_is_alive(runtime):
                        error = (
                            "Worker task cancelled"
                            if intent is WorkerTaskStatus.CANCELLED
                            else (
                                "Worker task timed out after "
                                f"{runtime.request.timeout_seconds}s"
                            )
                        )
                        self._finalize(
                            task_id,
                            intent,
                            error=error,
                            termination_confirmed=True,
                        )
                    else:
                        time.sleep(0.01)
                    continue
                if time.monotonic() >= runtime.deadline:
                    with self._lock:
                        if runtime.termination_intent is None:
                            runtime.termination_intent = WorkerTaskStatus.TIMEOUT
                        intent = runtime.termination_intent
                    if intent is not WorkerTaskStatus.TIMEOUT:
                        continue
                    confirmed = self._terminate(runtime)
                    if confirmed:
                        self._finalize(
                            task_id,
                            WorkerTaskStatus.TIMEOUT,
                            error=(
                                "Worker task timed out after "
                                f"{runtime.request.timeout_seconds}s"
                            ),
                            termination_confirmed=True,
                        )
                    else:
                        self._update_nonterminal_error(
                            task_id,
                            "Worker timeout could not confirm process termination",
                        )
                    continue
                if self._connection_ready(runtime.connection, 0.05):
                    self._receive_event(task_id, runtime)
                    with self._lock:
                        pending = runtime.pending_event
                if not self._process_is_alive(runtime):
                    self._join_process(runtime, timeout=0)
                    while self._connection_ready(runtime.connection):
                        self._receive_event(task_id, runtime)
                    with self._lock:
                        pending = runtime.pending_event
                        record = self._records.get(task_id)
                        intent = runtime.termination_intent
                        if record is not None and record.status.is_terminal:
                            return
                        if intent in {
                            WorkerTaskStatus.CANCELLED,
                            WorkerTaskStatus.TIMEOUT,
                        }:
                            error = (
                                "Worker task cancelled"
                                if intent is WorkerTaskStatus.CANCELLED
                                else (
                                    "Worker task timed out after "
                                    f"{runtime.request.timeout_seconds}s"
                                )
                            )
                            self._finalize(
                                task_id,
                                intent,
                                error=error,
                                termination_confirmed=True,
                            )
                        elif pending is not None:
                            if pending.kind is WorkerEventKind.RESULT:
                                self._finalize(
                                    task_id,
                                    WorkerTaskStatus.SUCCEEDED,
                                    result=pending.payload.get("result"),
                                    termination_confirmed=True,
                                )
                            else:
                                self._finalize(
                                    task_id,
                                    WorkerTaskStatus.FAILED,
                                    error=str(
                                        pending.payload.get("error", "Worker task failed")
                                    ),
                                    termination_confirmed=True,
                                )
                        else:
                            self._finalize(
                                task_id,
                                WorkerTaskStatus.CRASHED,
                                error=(
                                    "Worker process exited without a terminal event "
                                    f"(exit code {runtime.process.exitcode})"
                                ),
                                termination_confirmed=True,
                            )
                    return
        finally:
            self._cleanup_runtime(task_id)

    def _receive_event(self, task_id: str, runtime: _TaskRuntime) -> None:
        try:
            payload = json.loads(runtime.connection.recv_bytes().decode("utf-8"))
            event = WorkerEvent.from_dict(payload)
        except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return
        self._accept_event(task_id, event)

    @staticmethod
    def _connection_ready(connection: Connection, timeout: float = 0.0) -> bool:
        try:
            return connection.poll(timeout)
        except (BrokenPipeError, EOFError, OSError):
            return False

    def _accept_event(self, task_id: str, event: WorkerEvent) -> bool:
        with self._lock:
            runtime = self._runtimes.get(task_id)
            record = self._records.get(task_id)
            if runtime is None or record is None or record.status.is_terminal:
                return False
            if (
                runtime.termination_intent is not None
                or event.task_id != task_id
                or event.attempt_id != record.attempt_id
                or event.sequence <= record.last_event_sequence
                or runtime.pending_event is not None
            ):
                return False
            heartbeat = (
                event.timestamp
                if event.kind in {WorkerEventKind.STARTED, WorkerEventKind.HEARTBEAT}
                else record.last_heartbeat
            )
            self._records[task_id] = record.evolve(
                last_event_sequence=event.sequence,
                last_heartbeat=heartbeat,
            )
            if event.kind in {WorkerEventKind.RESULT, WorkerEventKind.FAILURE}:
                runtime.pending_event = event
            return True

    def _finalize(
        self,
        task_id: str,
        status: WorkerTaskStatus,
        *,
        result: object = None,
        error: str = "",
        termination_confirmed: bool,
    ) -> WorkerTaskRecord | None:
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return None
            if record.status.is_terminal:
                return record
            terminal = record.evolve(
                status=status,
                result=result,
                error=redact_text(error),
                termination_confirmed=termination_confirmed,
            )
            self._records[task_id] = terminal
            self._prune_records()
            if self._on_terminal is not None:
                try:
                    self._on_terminal(terminal)
                except Exception:
                    pass
            return terminal

    def _update_nonterminal_error(self, task_id: str, error: str) -> None:
        with self._lock:
            record = self._records.get(task_id)
            if record is not None and not record.status.is_terminal:
                self._records[task_id] = record.evolve(error=redact_text(error))

    @staticmethod
    def _process_is_alive(runtime: _TaskRuntime) -> bool:
        with runtime.process_lock:
            try:
                return runtime.process.is_alive()
            except ValueError:
                return False

    @staticmethod
    def _join_process(runtime: _TaskRuntime, timeout: float) -> None:
        with runtime.process_lock:
            try:
                runtime.process.join(timeout=timeout)
            except (AssertionError, ValueError):
                pass

    def _terminate(self, runtime: _TaskRuntime) -> bool:
        with runtime.process_lock:
            process = runtime.process
            try:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=self._termination_grace)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(timeout=self._termination_grace)
                return not process.is_alive()
            except ValueError:
                # Cleanup closes a handle only after confirming process exit.
                return True

    def _cleanup_runtime(self, task_id: str) -> None:
        with self._lock:
            runtime = self._runtimes.get(task_id)
            if runtime is None:
                return
            with runtime.process_lock:
                try:
                    if runtime.process.is_alive():
                        return
                except ValueError:
                    pass
                self._runtimes.pop(task_id, None)
                try:
                    runtime.connection.close()
                finally:
                    try:
                        runtime.process.join(timeout=0)
                    except (AssertionError, ValueError):
                        pass
                    try:
                        runtime.process.close()
                    except ValueError:
                        pass
            self._prune_records()

    def _prune_records(self) -> None:
        while len(self._records) > self._max_records:
            removable = next(
                (
                    task_id
                    for task_id, record in self._records.items()
                    if record.status.is_terminal and task_id not in self._runtimes
                ),
                None,
            )
            if removable is None:
                return
            self._records.pop(removable, None)
