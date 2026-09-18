"""
Multi-Agent Orchestrator - J.A.R.V.I.S. Phase 11

Lightweight native implementation of multi-agent coordination.

Features:
1. Agent registration with capability declarations
2. Task routing to registered agents by name
3. Concurrent task dispatch with per-task timeout control
4. Result collection and history tracking
5. Graceful shutdown with cleanup

Design principles:
- Zero external dependencies (stdlib only: threading, time, uuid, logging)
- Thread-based concurrency (Windows-safe, no signals)
- dataclass + asdict serialization, consistent with ollama_manager.py
"""

import logging
import threading
import time
import uuid
import warnings
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.brain.orchestrator_worker import (
    DeclaredAgentTaskError,
    DeclaredAgentWorker,
    ImportableAgentWorker,
)
from core.contracts.worker_protocol import WorkerTaskStatus

logger = logging.getLogger(__name__)

ORCHESTRATOR_HISTORY_LIMIT = 1000


class _AgentExecutionTimeout(TimeoutError):
    """A join deadline expired while the handler thread is still running."""

    def __init__(self, thread: threading.Thread, timeout: int) -> None:
        super().__init__(f"Handler exceeded {timeout}s timeout")
        self.thread = thread


# ============================================================
# Enums
# ============================================================

class AgentStatus(Enum):
    """Agent lifecycle status"""
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class TaskPriority(Enum):
    """Task priority levels"""
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


# ============================================================
# Data classes
# ============================================================

@dataclass
class AgentTask:
    """
    Task definition for dispatching to a registered agent.

    Attributes:
        task_id: Unique identifier (auto-generated if empty)
        agent_name: Target agent name (must be registered)
        prompt: Task prompt / input payload
        timeout: Maximum execution seconds (default 30)
        priority: Numeric priority (0=LOW, 1=MEDIUM, 2=HIGH, 3=CRITICAL)
        metadata: Arbitrary key-value metadata for routing or logging
    """
    task_id: str = ""
    agent_name: str = ""
    prompt: str = ""
    timeout: int = 30
    priority: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())[:8]


@dataclass
class AgentResult:
    """
    Result of a dispatched task.

    Attributes:
        task_id: Reference to the originating task
        agent_name: Agent that executed the task
        result: Agent output (any serializable type)
        error: Error message if execution failed
        duration_ms: Wall-clock execution time in milliseconds
        status: Outcome tag (success / error / timeout / busy)
    """
    task_id: str
    agent_name: str
    result: Any = None
    error: str = ""
    duration_ms: int = 0
    status: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (consistent with asdict usage in ollama_manager.py)"""
        return asdict(self)


@dataclass
class AgentInfo:
    """
    Agent registration info.

    Attributes:
        name: Unique agent name
        capabilities: List of capability strings (for routing)
        tasks_completed: Lifetime task count
        errors_count: Lifetime error count
        status: Current lifecycle status
    """
    name: str
    capabilities: List[str] = field(default_factory=list)
    tasks_completed: int = 0
    errors_count: int = 0
    status: str = AgentStatus.IDLE.value

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


# ============================================================
# Internal agent wrapper
# ============================================================

class _RegisteredAgent:
    """Internal wrapper tracking per-agent state."""

    def __init__(
        self,
        name: str,
        handler: Callable | None,
        capabilities: List[str],
        *,
        declared_worker: DeclaredAgentWorker | None = None,
    ):
        self.name = name
        self.handler = handler
        self.declared_worker = declared_worker
        self.capabilities = capabilities or []
        self.status = AgentStatus.IDLE
        self.current_task: Optional[AgentTask] = None
        self.tasks_completed = 0
        self.errors_count = 0
        self._error_recoverable = False
        self._pending_thread: Optional[threading.Thread] = None
        self._pending_declared_worker = False
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        with self._lock:
            self._reap_finished_execution_locked()
            return self.status == AgentStatus.IDLE

    def try_assign(self, task: AgentTask) -> bool:
        """Assign only when no previous handler execution remains active."""
        with self._lock:
            self._reap_finished_execution_locked()
            if self.status != AgentStatus.IDLE:
                return False
            self.current_task = task
            self.status = AgentStatus.BUSY
            self._error_recoverable = False
            return True

    def assign(self, task: AgentTask) -> None:
        with self._lock:
            self.current_task = task
            self.status = AgentStatus.BUSY
            self._error_recoverable = False

    def complete(self) -> None:
        with self._lock:
            self.tasks_completed += 1
            self.current_task = None
            self._error_recoverable = False
            if self.status != AgentStatus.SHUTDOWN:
                self.status = AgentStatus.IDLE

    def release_assignment(self) -> None:
        """Release a rejected pre-execution task without changing agent counters."""
        with self._lock:
            self.current_task = None
            self._error_recoverable = False
            if self.status != AgentStatus.SHUTDOWN:
                self.status = AgentStatus.IDLE

    def fail(self, *, recoverable: bool = True) -> None:
        with self._lock:
            self.errors_count += 1
            self.current_task = None
            self._error_recoverable = recoverable
            if self.status != AgentStatus.SHUTDOWN:
                self.status = AgentStatus.ERROR

    def reset(self) -> None:
        """Reset a completed error to IDLE so dispatch_with_retry can re-attempt."""
        with self._lock:
            self._reap_finished_execution_locked()
            if (
                self._pending_thread is not None
                or self._pending_declared_worker
                or self.status != AgentStatus.ERROR
            ):
                return
            self.status = AgentStatus.IDLE
            self.current_task = None
            self._error_recoverable = False

    def recover_from_error(self) -> bool:
        """Return a completed error state to IDLE without changing counters."""
        with self._lock:
            self._reap_finished_execution_locked()
            if self.status != AgentStatus.ERROR or not self._error_recoverable:
                return False
            self.status = AgentStatus.IDLE
            self.current_task = None
            self._error_recoverable = False
            return True

    def quarantine(self, thread: threading.Thread) -> None:
        """Keep the agent unavailable until a timed-out handler actually exits."""
        with self._lock:
            self._reap_finished_execution_locked()
            self.errors_count += 1
            if self.status != AgentStatus.SHUTDOWN:
                self.status = AgentStatus.ERROR
            self._error_recoverable = False
            self._pending_thread = thread

    def quarantine_declared_worker(self) -> None:
        """Keep an Agent unavailable while a Worker remains unconfirmed."""
        with self._lock:
            self._reap_finished_execution_locked()
            if not self._pending_declared_worker:
                self.errors_count += 1
            if self.status != AgentStatus.SHUTDOWN:
                self.status = AgentStatus.ERROR
            self._error_recoverable = False
            self._pending_declared_worker = True

    def has_pending_execution(self) -> bool:
        with self._lock:
            self._reap_finished_execution_locked()
            declared_pending = (
                self.declared_worker is not None
                and self._declared_worker_has_pending_locked()
            )
            return (
                self._pending_thread is not None
                or self._pending_declared_worker
                or declared_pending
            )

    def can_unregister(self) -> bool:
        with self._lock:
            self._reap_finished_execution_locked()
            return (
                self.status != AgentStatus.BUSY
                and self._pending_thread is None
                and not self._pending_declared_worker
            )

    def shutdown(self) -> None:
        declared_worker = self.declared_worker
        with self._lock:
            self.status = AgentStatus.SHUTDOWN
            self.current_task = None
            self._error_recoverable = False
        if declared_worker is not None:
            declared_worker.shutdown()

    def info(self) -> AgentInfo:
        with self._lock:
            self._reap_finished_execution_locked()
            return AgentInfo(
                name=self.name,
                capabilities=list(self.capabilities),
                tasks_completed=self.tasks_completed,
                errors_count=self.errors_count,
                status=self.status.value,
            )

    def _reap_finished_execution_locked(self) -> None:
        """Release timeout quarantine only after the daemon handler has stopped."""
        if self._pending_thread is not None:
            if self._pending_thread.is_alive():
                return
            self._pending_thread = None
            self.current_task = None
            self._error_recoverable = False
            if self.status != AgentStatus.SHUTDOWN:
                self.status = AgentStatus.IDLE

        if not self._pending_declared_worker:
            return
        if (
            self.declared_worker is not None
            and self._declared_worker_has_pending_locked()
        ):
            return
        self._pending_declared_worker = False
        self.current_task = None
        self._error_recoverable = False
        if self.status != AgentStatus.SHUTDOWN:
            self.status = AgentStatus.IDLE

    def _declared_worker_has_pending_locked(self) -> bool:
        """Treat a failed Worker state probe as pending until proven safe."""
        if self.declared_worker is None:
            return False
        try:
            return self.declared_worker.has_pending_execution()
        except Exception:
            logger.exception("Unable to confirm declared agent '%s' termination", self.name)
            return True


# ============================================================
# Orchestrator
# ============================================================

class Orchestrator:
    """
    Multi-Agent Orchestrator - coordinates task dispatch across registered agents.

    Usage:
        orch = Orchestrator(default_timeout=30)

        def handle_analyze(task):
            return {"summary": "..."}

        orch.register_in_process(
            "analyzer",
            handle_analyze,
            capabilities=["analysis", "summarization"],
        )

        result = orch.dispatch(AgentTask(
            task_id="t1",
            agent_name="analyzer",
            prompt="Summarize this codebase",
        ))

        history = orch.collect(limit=10)
        orch.shutdown()
    """

    def __init__(self, default_timeout: int = 30):
        self._agents: Dict[str, _RegisteredAgent] = {}
        self._agents_lock = threading.Lock()
        self._retry_attempt_source = threading.local()
        self._history: deque[AgentResult] = deque(
            maxlen=ORCHESTRATOR_HISTORY_LIMIT
        )
        self._history_lock = threading.Lock()
        self._default_timeout = default_timeout
        self._shutdown = False
        self._stats = {
            "total_dispatched": 0,
            "total_success": 0,
            "total_errors": 0,
            "total_timeouts": 0,
        }

    # ============================================================
    # Registration
    # ============================================================

    def register(
        self,
        name: str,
        handler: Callable[[AgentTask], Any],
        capabilities: Optional[List[str]] = None,
    ) -> "Orchestrator":
        """Register an in-process agent through the deprecated compatibility API."""
        warnings.warn(
            "Orchestrator.register() is deprecated; use register_worker() for "
            "stable importable top-level functions or register_in_process() for "
            "intentional process-local execution.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.register_in_process(name, handler, capabilities)

    def register_in_process(
        self,
        name: str,
        handler: Callable[[AgentTask], Any],
        capabilities: Optional[List[str]] = None,
    ) -> "Orchestrator":
        """Register a process-local, thread-backed task handler."""
        displaced_agent = None
        with self._agents_lock:
            current_agent = self._agents.get(name)
            if current_agent is not None:
                if not current_agent.can_unregister():
                    logger.warning(f"Cannot re-register active agent '{name}'")
                    return self
                logger.warning(f"Agent '{name}' re-registered (replacing existing)")
                displaced_agent = current_agent
            self._agents[name] = _RegisteredAgent(name, handler, capabilities or [])
        if displaced_agent is not None and displaced_agent.declared_worker is not None:
            displaced_agent.shutdown()
        logger.info(f"Agent registered: '{name}' capabilities={capabilities}")
        return self

    def register_declared(
        self,
        name: str,
        runner_id: str,
        capabilities: Optional[List[str]] = None,
    ) -> "Orchestrator":
        """Register an opt-in Agent backed by a static child-process runner."""
        declared_worker = DeclaredAgentWorker(name, runner_id)
        displaced_agent = None
        with self._agents_lock:
            current_agent = self._agents.get(name)
            if current_agent is not None:
                if not current_agent.can_unregister():
                    logger.warning(f"Cannot re-register active agent '{name}'")
                    return self
                logger.warning(f"Agent '{name}' re-registered (replacing existing)")
                displaced_agent = current_agent
            self._agents[name] = _RegisteredAgent(
                name,
                None,
                capabilities or [],
                declared_worker=declared_worker,
            )
        if displaced_agent is not None and displaced_agent.declared_worker is not None:
            displaced_agent.shutdown()
        logger.info(
            "Declared agent registered: '%s' runner=%s capabilities=%s",
            name,
            runner_id,
            capabilities,
        )
        return self

    def register_worker(
        self,
        name: str,
        handler: Callable[[AgentTask], Any],
        capabilities: Optional[List[str]] = None,
    ) -> "Orchestrator":
        """Register an importable top-level callable in a child Worker."""
        worker = ImportableAgentWorker(name, handler)
        displaced_agent = None
        with self._agents_lock:
            current_agent = self._agents.get(name)
            if current_agent is not None:
                if not current_agent.can_unregister():
                    worker.shutdown()
                    logger.warning(f"Cannot re-register active agent '{name}'")
                    return self
                logger.warning(f"Agent '{name}' re-registered (replacing existing)")
                displaced_agent = current_agent
            self._agents[name] = _RegisteredAgent(
                name,
                None,
                capabilities or [],
                declared_worker=worker,
            )
        if displaced_agent is not None and displaced_agent.declared_worker is not None:
            displaced_agent.shutdown()
        logger.info(
            "Importable Worker agent registered: '%s' handler=%s.%s capabilities=%s",
            name,
            worker.module_name,
            worker.function_name,
            capabilities,
        )
        return self

    def unregister(self, name: str) -> bool:
        """Unregister an agent. Fails if currently busy."""
        with self._agents_lock:
            agent = self._agents.get(name)
            if agent is None:
                return False
            if not agent.can_unregister():
                logger.warning(f"Cannot unregister active agent '{name}'")
                return False
            del self._agents[name]
        if agent.declared_worker is not None:
            agent.shutdown()
        logger.info(f"Agent unregistered: '{name}'")
        return True

    def recover_agent(self, name: str) -> bool:
        """Recover a registered agent only when its current state is ERROR."""
        with self._agents_lock:
            agent = self._agents.get(name)
            if agent is None:
                return False
            return agent.recover_from_error()

    def cancel(self, agent_name: str, task_id: str) -> bool:
        """Cancel a Worker-backed task after confirmed child termination."""
        with self._agents_lock:
            agent = self._agents.get(agent_name)
        if agent is None or agent.declared_worker is None:
            return False
        record = agent.declared_worker.cancel(task_id)
        return bool(
            record is not None
            and record.status is WorkerTaskStatus.CANCELLED
            and record.termination_confirmed
        )

    def list_agents(self) -> List[AgentInfo]:
        """Return info for all registered agents."""
        with self._agents_lock:
            agents = list(self._agents.values())
        return [agent.info() for agent in agents]

    # ============================================================
    # Dispatch
    # ============================================================

    def dispatch(self, task: AgentTask) -> AgentResult:
        """Dispatch a single task to its target agent."""
        self._stats["total_dispatched"] += 1
        agent_name = task.agent_name

        with self._agents_lock:
            if self._shutdown:
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=agent_name,
                    error="Orchestrator is shutting down",
                    status="error",
                )

            agent = self._agents.get(agent_name)
            if agent is None:
                self._stats["total_errors"] += 1
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=agent_name,
                    error=f"Agent '{agent_name}' not found",
                    status="error",
                )

            if not agent.try_assign(task):
                self._stats["total_errors"] += 1
                return AgentResult(
                    task_id=task.task_id,
                    agent_name=agent_name,
                    error=f"Agent '{agent_name}' is busy",
                    status="busy",
                )

            retry_attempt_source = getattr(
                self._retry_attempt_source, "value", None
            )
            if retry_attempt_source is not None:
                retry_attempt_source.append(agent.declared_worker is not None)

        start = time.perf_counter()

        if agent.declared_worker is not None:
            return self._dispatch_declared(agent, task, start)

        try:
            output = self._run_with_timeout(agent.handler, task, task.timeout)
            duration_ms = int((time.perf_counter() - start) * 1000)
            agent.complete()
            self._stats["total_success"] += 1

            if isinstance(output, AgentResult):
                output.duration_ms = duration_ms
                self._record(output)
                return output

            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                result=output,
                duration_ms=duration_ms,
                status="success",
            )
            self._record(result)
            return result

        except _AgentExecutionTimeout as error:
            duration_ms = int((time.perf_counter() - start) * 1000)
            agent.quarantine(error.thread)
            self._stats["total_timeouts"] += 1
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=f"Task timed out after {task.timeout}s",
                duration_ms=duration_ms,
                status="timeout",
            )
            self._record(result)
            logger.error(f"Task '{task.task_id}' timed out on agent '{agent_name}'")
            return result

        except TimeoutError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            agent.fail(recoverable=False)
            self._stats["total_timeouts"] += 1
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=f"Task timed out after {task.timeout}s",
                duration_ms=duration_ms,
                status="timeout",
            )
            self._record(result)
            logger.error(f"Task '{task.task_id}' timed out on agent '{agent_name}'")
            return result

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            agent.fail()
            self._stats["total_errors"] += 1
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=str(exc),
                duration_ms=duration_ms,
                status="error",
            )
            self._record(result)
            logger.error(f"Task '{task.task_id}' error on agent '{agent_name}': {exc}")
            return result

    def _dispatch_declared(
        self,
        agent: _RegisteredAgent,
        task: AgentTask,
        start: float,
    ) -> AgentResult:
        """Map a confirmed static Worker record into the generic result shape."""
        agent_name = task.agent_name
        try:
            record = agent.declared_worker.dispatch(
                task_id=task.task_id,
                agent_name=agent_name,
                prompt=task.prompt,
                timeout=task.timeout,
                priority=task.priority,
                metadata=task.metadata,
            )
        except DeclaredAgentTaskError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            agent.release_assignment()
            self._stats["total_errors"] += 1
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=str(exc),
                duration_ms=duration_ms,
                status="error",
            )
            self._record(result)
            logger.error(
                "Task '%s' rejected by declared agent '%s': %s",
                task.task_id,
                agent_name,
                exc,
            )
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if agent.has_pending_execution():
                agent.quarantine_declared_worker()
            else:
                agent.fail()
            self._stats["total_errors"] += 1
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=str(exc),
                duration_ms=duration_ms,
                status="error",
            )
            self._record(result)
            logger.error(
                "Task '%s' error on declared agent '%s': %s",
                task.task_id,
                agent_name,
                exc,
            )
            return result

        duration_ms = int((time.perf_counter() - start) * 1000)
        if (
            record is None
            or not record.status.is_terminal
            or not record.termination_confirmed
        ):
            agent.quarantine_declared_worker()
            self._stats["total_timeouts"] += 1
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=f"Task timed out after {task.timeout}s",
                duration_ms=duration_ms,
                status="timeout",
            )
            self._record(result)
            logger.error(
                "Task '%s' timed out on declared agent '%s' without confirmed termination",
                task.task_id,
                agent_name,
            )
            return result

        if record.status is WorkerTaskStatus.SUCCEEDED:
            try:
                output = agent.declared_worker.decode_result(record.result)
            except Exception as exc:
                agent.fail()
                self._stats["total_errors"] += 1
                result = AgentResult(
                    task_id=task.task_id,
                    agent_name=agent_name,
                    error=str(exc),
                    duration_ms=duration_ms,
                    status="error",
                )
                self._record(result)
                logger.error(
                    "Task '%s' returned an invalid Worker result: %s",
                    task.task_id,
                    exc,
                )
                return result
            agent.complete()
            self._stats["total_success"] += 1
            if isinstance(output, AgentResult):
                output.duration_ms = duration_ms
                self._record(output)
                return output
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                result=output,
                duration_ms=duration_ms,
                status="success",
            )
            self._record(result)
            return result

        if record.status is WorkerTaskStatus.TIMEOUT:
            agent.fail(recoverable=False)
            self._stats["total_timeouts"] += 1
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=f"Task timed out after {task.timeout}s",
                duration_ms=duration_ms,
                status="timeout",
            )
            self._record(result)
            logger.error(
                "Task '%s' timed out on declared agent '%s'",
                task.task_id,
                agent_name,
            )
            return result

        if record.status is WorkerTaskStatus.CANCELLED:
            agent.release_assignment()
            result = AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=record.error or "Worker task cancelled",
                duration_ms=duration_ms,
                status="cancelled",
            )
            self._record(result)
            return result

        agent.fail()
        self._stats["total_errors"] += 1
        result = AgentResult(
            task_id=task.task_id,
            agent_name=agent_name,
            error=record.error or "Declared agent worker failed",
            duration_ms=duration_ms,
            status="error",
        )
        self._record(result)
        logger.error(
            "Task '%s' failed on declared agent '%s': %s",
            task.task_id,
            agent_name,
            result.error,
        )
        return result

    def dispatch_with_retry(
        self,
        task: AgentTask,
        max_retries: int = 2,
        backoff_factor: float = 1.0,
    ) -> AgentResult:
        """Dispatch with automatic retry on timeout / busy transient error.

        Args:
            task: The task to dispatch.
            max_retries: Maximum retry count after the first attempt (default 2).
            backoff_factor: Sleep duration multiplier: backoff_factor * (attempt+1) seconds.

        Returns:
            AgentResult from the successful attempt or the last failed attempt.
        """
        last_result = None
        last_attempt_declared = False
        for attempt in range(max_retries + 1):
            # Reset agent if stuck in ERROR from a previous attempt
            with self._agents_lock:
                agent = self._agents.get(task.agent_name)
                if attempt > 0 and agent is not None:
                    agent.reset()
            attempt_source = []
            previous_source = getattr(self._retry_attempt_source, "value", None)
            self._retry_attempt_source.value = attempt_source
            try:
                result = self.dispatch(task)
            finally:
                self._retry_attempt_source.value = previous_source
            last_result = result
            last_attempt_declared = attempt_source[0] if attempt_source else False
            if result.status == "success":
                # immediate success: record retry_stats and return
                self._stats.setdefault("total_retries", 0)
                if attempt > 0:
                    self._stats["total_retries"] += attempt
                return result
            if result.status in ("busy", "timeout"):
                with self._agents_lock:
                    agent = self._agents.get(task.agent_name)
                if agent is not None and agent.has_pending_execution():
                    return result
                # transient: retry if attempts remain
                if attempt < max_retries:
                    wait = backoff_factor * (attempt + 1)
                    logger.warning(
                        f"Task {task.task_id!r} attempt {attempt+1}/{max_retries} "
                        f"transient ({result.status}), retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
                    continue
                # exhausted: fall through to failed below
                break
            # error status: do not retry
            break
        # All retries exhausted
        if last_result is not None:
            if last_attempt_declared:
                return last_result

            last_result.status = "failed"
            last_result.error = (last_result.error or "") + f" [after {max_retries} retries]"
            self._record(last_result)
            self._stats.setdefault("total_errors", 0)
            self._stats["total_errors"] += 1
            return last_result
        return None

    def dispatch_concurrent(self, tasks: List[AgentTask]) -> List[AgentResult]:
        """Dispatch multiple tasks concurrently, one thread per task."""
        results: List[AgentResult] = []
        results_lock = threading.Lock()
        threads: List[threading.Thread] = []

        def _run(t: AgentTask) -> None:
            r = self.dispatch(t)
            with results_lock:
                results.append(r)

        for task in tasks:
            thread = threading.Thread(target=_run, args=(task,), daemon=True)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        return results

    # ============================================================
    # Collection
    # ============================================================

    def collect(
        self,
        task_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentResult]:
        """Retrieve task results from history with optional filters."""
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []
        with self._history_lock:
            entries = [
                result
                for result in reversed(self._history)
                if (task_id is None or result.task_id == task_id)
                and (agent_name is None or result.agent_name == agent_name)
                and (status is None or result.status == status)
            ][:limit]

        return deepcopy(entries)

    def get_stats(self) -> Dict[str, int]:
        """Return aggregate dispatch statistics."""
        return dict(self._stats)

    # ============================================================
    # Lifecycle
    # ============================================================

    def shutdown(self) -> None:
        """Graceful shutdown: close orchestrator, set agents to SHUTDOWN."""
        with self._agents_lock:
            self._shutdown = True
            agents = list(self._agents.values())
        with self._history_lock:
            for agent in agents:
                agent.shutdown()
        logger.info(f"Orchestrator shutdown. Stats: {self._stats}")

    # ============================================================
    # Internal
    # ============================================================

    def _run_with_timeout(
        self,
        handler: Callable,
        task: AgentTask,
        timeout: int,
    ) -> Any:
        """Execute handler in a daemon thread with join-timeout."""
        result_holder: List[Any] = [None]
        error_holder: List[Optional[Exception]] = [None]

        def _target() -> None:
            try:
                result_holder[0] = handler(task)
            except Exception as exc:
                error_holder[0] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise _AgentExecutionTimeout(thread, timeout)

        if error_holder[0] is not None:
            raise error_holder[0]

        return result_holder[0]

    def _record(self, result: AgentResult) -> None:
        """Append result to history (thread-safe)."""
        snapshot = deepcopy(result)
        with self._history_lock:
            self._history.append(snapshot)
