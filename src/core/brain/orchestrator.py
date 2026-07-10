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
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


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

    def __init__(self, name: str, handler: Callable, capabilities: List[str]):
        self.name = name
        self.handler = handler
        self.capabilities = capabilities or []
        self.status = AgentStatus.IDLE
        self.current_task: Optional[AgentTask] = None
        self.tasks_completed = 0
        self.errors_count = 0
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        with self._lock:
            return self.status == AgentStatus.IDLE

    def assign(self, task: AgentTask) -> None:
        with self._lock:
            self.current_task = task
            self.status = AgentStatus.BUSY

    def complete(self) -> None:
        with self._lock:
            self.tasks_completed += 1
            self.status = AgentStatus.IDLE
            self.current_task = None

    def fail(self) -> None:
        with self._lock:
            self.errors_count += 1
            self.status = AgentStatus.ERROR
            self.current_task = None

    def reset(self) -> None:
        """Reset to IDLE so dispatch_with_retry can re-attempt."""
        with self._lock:
            self.status = AgentStatus.IDLE
            self.current_task = None

    def info(self) -> AgentInfo:
        with self._lock:
            return AgentInfo(
                name=self.name,
                capabilities=list(self.capabilities),
                tasks_completed=self.tasks_completed,
                errors_count=self.errors_count,
                status=self.status.value,
            )


# ============================================================
# Orchestrator
# ============================================================

class Orchestrator:
    """
    Multi-Agent Orchestrator - coordinates task dispatch across registered agents.

    Usage:
        orch = Orchestrator(default_timeout=30)

        @orch.register("analyzer", capabilities=["analysis", "summarization"])
        def handle_analyze(task):
            return {"summary": "..."}

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
        self._history: List[AgentResult] = []
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
        """Register an agent with a task handler. Returns self for chaining."""
        if name in self._agents:
            logger.warning(f"Agent '{name}' re-registered (replacing existing)")
        self._agents[name] = _RegisteredAgent(name, handler, capabilities or [])
        logger.info(f"Agent registered: '{name}' capabilities={capabilities}")
        return self

    def unregister(self, name: str) -> bool:
        """Unregister an agent. Fails if currently busy."""
        if name not in self._agents:
            return False
        agent = self._agents[name]
        if agent.status == AgentStatus.BUSY:
            logger.warning(f"Cannot unregister busy agent '{name}'")
            return False
        del self._agents[name]
        logger.info(f"Agent unregistered: '{name}'")
        return True

    def list_agents(self) -> List[AgentInfo]:
        """Return info for all registered agents."""
        return [a.info() for a in self._agents.values()]

    # ============================================================
    # Dispatch
    # ============================================================

    def dispatch(self, task: AgentTask) -> AgentResult:
        """Dispatch a single task to its target agent."""
        self._stats["total_dispatched"] += 1
        agent_name = task.agent_name

        if self._shutdown:
            return AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error="Orchestrator is shutting down",
                status="error",
            )

        if agent_name not in self._agents:
            self._stats["total_errors"] += 1
            return AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=f"Agent '{agent_name}' not found",
                status="error",
            )

        agent = self._agents[agent_name]

        if not agent.is_available():
            self._stats["total_errors"] += 1
            return AgentResult(
                task_id=task.task_id,
                agent_name=agent_name,
                error=f"Agent '{agent_name}' is busy",
                status="busy",
            )

        agent.assign(task)
        start = time.perf_counter()

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

        except TimeoutError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            agent.fail()
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
        for attempt in range(max_retries + 1):
            # Reset agent if stuck in ERROR from a previous attempt
            if attempt > 0 and task.agent_name in self._agents:
                self._agents[task.agent_name].reset()
            result = self.dispatch(task)
            last_result = result
            if result.status == "success":
                # immediate success: record retry_stats and return
                self._stats.setdefault("total_retries", 0)
                if attempt > 0:
                    self._stats["total_retries"] += attempt
                return result
            if result.status in ("busy", "timeout"):
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
            last_result.status = "failed"
            last_result.error = (last_result.error or "") + f" [after {max_retries} retries]"
            self._record(last_result)
            self._stats.setdefault("total_errors", 0)
            self._stats["total_errors"] += 1
        return last_result

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
        with self._history_lock:
            entries = list(reversed(self._history[-limit:]))

        if task_id is not None:
            entries = [r for r in entries if r.task_id == task_id]
        if agent_name is not None:
            entries = [r for r in entries if r.agent_name == agent_name]
        if status is not None:
            entries = [r for r in entries if r.status == status]

        return entries

    def get_stats(self) -> Dict[str, int]:
        """Return aggregate dispatch statistics."""
        return dict(self._stats)

    # ============================================================
    # Lifecycle
    # ============================================================

    def shutdown(self) -> None:
        """Graceful shutdown: close orchestrator, set agents to SHUTDOWN."""
        self._shutdown = True
        with self._history_lock:
            for agent in self._agents.values():
                agent.status = AgentStatus.SHUTDOWN
                agent.current_task = None
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
            raise TimeoutError(f"Handler exceeded {timeout}s timeout")

        if error_holder[0] is not None:
            raise error_holder[0]

        return result_holder[0]

    def _record(self, result: AgentResult) -> None:
        """Append result to history (thread-safe)."""
        with self._history_lock:
            self._history.append(result)
