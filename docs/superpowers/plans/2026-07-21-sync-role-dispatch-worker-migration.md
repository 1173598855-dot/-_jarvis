# Synchronous Role Dispatch Worker Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all legacy synchronous role dispatch routes onto the terminable process Worker boundary while preserving their public request and response contracts.

**Architecture:** `RoleWorkerSupervisor` remains the sole owner of execution deadlines and confirmed process termination. A new brain-layer `RoleDispatchService` owns compatibility role leases, Worker submit/wait, strict terminal decoding, and sequential batch behavior; both Python adapters compose that service, while Express stays a transparent proxy with a request budget long enough for the Core deadline.

**Tech Stack:** Python 3.10+ standard library multiprocessing/threading/dataclasses, existing FastAPI and Ollama manager, Node.js/Express, OpenAPI 3.1 JSON, unittest, Vitest, and Playwright.

## Global Constraints

- Worker protocol version remains exactly `1`.
- Request timeout remains a strict non-boolean integer from `1` through `300` seconds.
- The parent `RoleWorkerSupervisor` is the only deadline and termination authority for migrated routes.
- A public `timeout` result requires a terminal Worker record with `termination_confirmed=true`.
- A nonterminal or unconfirmed record maps to `503 ROLE_TASK_TERMINATION_UNCONFIRMED`, and its synchronous role lease remains held.
- Successful Worker payloads contain exactly four string dispatch fields: `role_name`, `task_id`, `status`, and `message`; the inner role must match the selected role.
- The public synchronous task ID is always the outer Worker task ID.
- Token usage is recorded exactly once by a Supervisor terminal observer.
- Synchronous compatibility leases do not change `/api/roles/tasks` concurrency semantics.
- Batch dispatch is sequential and preserves one result per input position.
- HTTP input cannot choose a Worker task ID, runner, command, environment, working directory, or capability token.
- `/api/orchestrator/dispatch`, task persistence/recovery, and model tool loops remain outside this iteration.
- New behavior follows red-green-refactor, and each task ends with a focused commit.
- Preserve the unrelated working-tree deletion of `RISK_COMPONENTS.log`; never stage or restore it.

---

## File Structure

- `src/core/brain/role_worker.py`: condition-based record waiting, terminal observer fan-out, lock-safe terminal publication, and the fixed direct role runner.
- `src/core/brain/agent_factory.py`: shared role-task construction plus one direct, non-Orchestrator execution primitive.
- `src/core/kernel/ollama_manager.py`: allow `timeout=None` only when a caller deliberately disables the HTTP transport deadline.
- `src/core/brain/role_dispatch_service.py`: synchronous compatibility role selection, leases, Worker mapping, and batch normalization.
- `src/main_fastapi.py`: asynchronous HTTP adapter using `asyncio.to_thread` and shared application lifecycle ownership.
- `src/main.py`: standard-library HTTP adapter with injectable server state and complete shutdown ownership.
- `frontend/server/core-api.js` and `frontend/server.js`: transparent proxy with a per-request timeout override for bounded synchronous role requests.
- `contracts/core-api.openapi.json`: OpenAPI `1.13.0` descriptions and stable `503` outcomes.
- Focused test modules mirror each ownership boundary; aggregate and iteration documents record only measured final evidence.

---

### Task 1: Waitable, Observable Supervisor Publication

**Files:**
- Modify: `src/core/brain/role_worker.py:196-674`
- Modify: `tests/test_role_worker.py:51-698`

**Interfaces:**
- Produces: `RoleWorkerSupervisor.wait(task_id: str, timeout: float) -> WorkerTaskRecord | None`.
- Produces: `RoleWorkerSupervisor.terminal_wait_budget(timeout_seconds: int) -> float` as the only compatibility wait-budget calculation.
- Produces: `RoleWorkerSupervisor.add_terminal_observer(observer: Callable[[WorkerTaskRecord], None]) -> None`.
- Preserves: constructor argument `on_terminal` by installing it as the first observer.
- Guarantees: all record changes that can unblock a waiter notify one shared `threading.Condition`; observers run after every recursive Supervisor lock acquisition has been released.
- Guarantees: records with an active waiter cannot be pruned between terminal notification and waiter lock reacquisition.

- [ ] **Step 1: Write the failing wait and observer tests.**

Add these exact cases to `TestRoleWorkerSupervisor`: `test_wait_returns_none_for_unknown_task`, `test_wait_returns_current_record_when_budget_expires`, `test_wait_is_notified_by_success_and_confirmed_timeout`, `test_wait_rejects_invalid_timeout`, `test_terminal_wait_budget_covers_deadline_and_both_termination_graces`, `test_terminal_observers_are_isolated_and_run_outside_supervisor_lock`, and `test_terminal_observer_runs_before_record_can_be_pruned`. Use the existing `succeed` and `sleep_then_succeed` spawn fixtures. In the lock test, block the first observer on an event, prove separate threads can complete `get`, `list`, and `wait` before releasing it, then prove a raising observer does not suppress the final observer.

- [ ] **Step 2: Run the focused tests and verify RED.**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_worker.TestRoleWorkerSupervisor.test_wait_returns_none_for_unknown_task tests.test_role_worker.TestRoleWorkerSupervisor.test_wait_returns_current_record_when_budget_expires tests.test_role_worker.TestRoleWorkerSupervisor.test_wait_is_notified_by_success_and_confirmed_timeout tests.test_role_worker.TestRoleWorkerSupervisor.test_wait_rejects_invalid_timeout tests.test_role_worker.TestRoleWorkerSupervisor.test_terminal_observers_are_isolated_and_run_outside_supervisor_lock tests.test_role_worker.TestRoleWorkerSupervisor.test_terminal_observer_runs_before_record_can_be_pruned -v
```

Expected: FAIL because `wait` and `add_terminal_observer` do not exist and terminal callbacks still run under the recursive lock.

- [ ] **Step 3: Implement the condition and observer API.**

Use this public shape and validation:

```python
self._terminal_observers: list[Callable[[WorkerTaskRecord], None]] = []
if on_terminal is not None:
    if not callable(on_terminal):
        raise TypeError("on_terminal must be callable")
    self._terminal_observers.append(on_terminal)
self._lock = threading.RLock()
self._condition = threading.Condition(self._lock)
self._waiters: dict[str, int] = {}

MONITOR_WAIT_SLACK = 0.25

def terminal_wait_budget(self, timeout_seconds: int) -> float:
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= 300
    ):
        raise ValueError("timeout_seconds must be an integer from 1 through 300")
    return (
        float(timeout_seconds)
        + (2 * self._termination_grace)
        + MONITOR_WAIT_SLACK
    )

def add_terminal_observer(
    self,
    observer: Callable[[WorkerTaskRecord], None],
) -> None:
    if not callable(observer):
        raise TypeError("observer must be callable")
    with self._condition:
        self._terminal_observers.append(observer)

def wait(self, task_id: str, timeout: float) -> WorkerTaskRecord | None:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout < 0
    ):
        raise ValueError("timeout must be a finite non-negative number")
    deadline = time.monotonic() + float(timeout)
    with self._condition:
        record = self._records.get(task_id)
        if record is None:
            return None
        self._waiters[task_id] = self._waiters.get(task_id, 0) + 1
        try:
            while not record.status.is_terminal:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return record
                self._condition.wait(remaining)
                latest = self._records.get(task_id)
                if latest is None:
                    return None
                record = latest
            return record
        finally:
            remaining_waiters = self._waiters[task_id] - 1
            if remaining_waiters:
                self._waiters[task_id] = remaining_waiters
            else:
                self._waiters.pop(task_id, None)
            self._prune_records()
```

Refactor `_monitor` so the block currently beginning near line 473 only computes a terminal decision while holding `_lock`; call `_finalize` after leaving that outer block. `_finalize` stores the record, calls `notify_all()`, and copies observers under `_condition`, then invokes the copied observers one by one outside all Supervisor locks with `try/except Exception`. Keep runtime cleanup after observer delivery so a finalized record cannot be pruned before its lease-release observer sees it. Make `_prune_records` exclude IDs present in `_waiters`. Notify after submit publication, cancellation/error mutation, runtime cleanup, and pruning when those mutations can change a wait result.

- [ ] **Step 4: Run the complete Supervisor regression module.**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_worker -v
```

Expected: all tests pass; timeout/cancel still require confirmed process death, and every test-owned process is dead in teardown.

- [ ] **Step 5: Commit the independently reviewable Supervisor change.**

```powershell
git add src/core/brain/role_worker.py tests/test_role_worker.py
git commit -m "feat: make role worker completion waitable"
```

---

### Task 2: Single-Deadline Fixed Role Execution

**Files:**
- Modify: `src/core/brain/agent_factory.py:57-146`
- Modify: `src/core/brain/role_worker.py:28-75`
- Modify: `src/core/kernel/ollama_manager.py:79-84`
- Modify: `tests/test_agent_factory.py:270-420`
- Modify: `tests/test_role_worker.py:663-698`

**Interfaces:**
- Produces: `AgentFactory.execute_role_once(role_name: str, task_prompt: str, *, task_id: str) -> DispatchResult`.
- Produces: private `_build_role_task(profile, task_prompt, *, task_id, timeout) -> AgentTask` shared by direct and legacy dispatch.
- Consumes: the selected role profile, authorized tool metadata, and existing `_default_handler` normalization.
- Guarantees: the direct method never calls `Orchestrator.dispatch`, `_run_with_timeout`, or registers a nested role agent.

- [ ] **Step 1: Write failing direct-execution tests.**

Add `test_execute_role_once_invokes_resolved_handler_without_orchestrator_dispatch`, `test_execute_role_once_preserves_prompt_and_authorized_tool_metadata`, `test_execute_role_once_sanitizes_handler_failure`, and `test_execute_role_once_returns_no_role`. Assert the supplied outer task ID is preserved, `orchestrator.dispatch` is not called, system/user prompts and tool metadata match legacy dispatch, and handler failures expose only `ROLE_EXECUTION_ERROR`.

Add `test_fixed_role_runner_uses_direct_execution_without_transport_timeout` to call `execute_role_task` with patched local imports and assert this exact interaction:

```python
manager_type.assert_called_once_with(
    base_url="http://fixture.local",
    timeout=None,
)
factory.execute_role_once.assert_called_once_with(
    "engineer",
    "inspect",
    task_id=request.task_id,
)
factory.dispatch_by_role.assert_not_called()
```

- [ ] **Step 2: Run the direct-execution tests and verify RED.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory.TestOllamaRoleExecution.test_execute_role_once_invokes_resolved_handler_without_orchestrator_dispatch tests.test_agent_factory.TestOllamaRoleExecution.test_execute_role_once_preserves_prompt_and_authorized_tool_metadata tests.test_agent_factory.TestOllamaRoleExecution.test_execute_role_once_sanitizes_handler_failure tests.test_role_worker.TestRoleWorkerSupervisor.test_fixed_role_runner_uses_direct_execution_without_transport_timeout -v
```

Expected: FAIL because `execute_role_once` is absent and the runner still passes the request timeout into both Ollama and Orchestrator.

- [ ] **Step 3: Extract task construction and implement direct execution.**

Implement the direct path with the existing handler contract:

```python
def execute_role_once(
    self,
    role_name: str,
    task_prompt: str,
    *,
    task_id: str,
) -> DispatchResult:
    profile = self.registry.get(role_name)
    if profile is None:
        return DispatchResult(
            role_name,
            task_id,
            "no_role",
            f"Role '{role_name}' not found",
        )
    task = self._build_role_task(
        profile,
        task_prompt,
        task_id=task_id,
        timeout=300,
    )
    try:
        output = self._default_handler(profile)(task)
    except Exception:
        logger.warning("Direct role execution failed for role %s", profile.name)
        return DispatchResult(role_name, task_id, "error", ROLE_EXECUTION_ERROR)
    return DispatchResult(role_name, task_id, "success", output)
```

Move lines 69-92 into `_build_role_task` without changing metadata. Legacy `dispatch_by_role` passes its current hash-derived ID and caller timeout. Change `OllamaManager.__init__` to `timeout: Optional[int] = 30`, and construct the child manager with `timeout=None`. Change the fixed runner to call `execute_role_once(..., task_id=request.task_id)`; keep usage collection and `factory.shutdown()` unchanged.

- [ ] **Step 4: Run all affected execution tests.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory tests.test_role_worker tests.test_ollama_manager tests.test_ollama_manager_extended -v
```

Expected: all tests pass, including the real local Ollama Worker fixture and parent token accounting.

- [ ] **Step 5: Commit the single-deadline runner change.**

```powershell
git add src/core/brain/agent_factory.py src/core/brain/role_worker.py src/core/kernel/ollama_manager.py tests/test_agent_factory.py tests/test_role_worker.py
git commit -m "fix: make role worker the sole dispatch deadline"
```

---

### Task 3: Shared Synchronous Role Dispatch Service

**Files:**
- Create: `src/core/brain/role_dispatch_service.py`
- Create: `tests/test_role_dispatch_service.py`

**Interfaces:**
- Produces: `RoleDispatchService(registry, supervisor, *, task_id_factory=None)`.
- Produces: `dispatch_by_role`, `dispatch_by_capability`, and `batch_dispatch` with the same signatures as `AgentFactory` compatibility methods.
- Produces: `RoleWorkerUnavailableError`, `RoleTaskTerminationUnconfirmedError`, and `RoleWorkerInvalidResultError`, each retaining `role_name`, `task_id`, and a stable message.
- Consumes: `RoleRegistry`, `RoleWorkerSupervisor`, `WorkerTaskRequest`, `WorkerTaskRecord`, `WorkerTaskStatus`, and `DispatchResult`.

- [ ] **Step 1: Write the service contract tests.**

Create spawn-free fake Supervisor records and cover these exact behaviors: role and highest-priority capability selection; unknown role/capability without submit; outer ID replacing inner ID; strict success decoding for extra/missing/non-string/wrong-role payloads; confirmed timeout; stable failed/crashed/cancelled mapping; nonterminal and terminal-unconfirmed lease retention; busy result with a new ID and no Worker history entry; observer release and same-role reuse; submit failure with no record rolling the reservation back; submit failure with an established record retaining it; a missing pruned terminal lease becoming reusable; and task IDs that satisfy the Worker identifier contract. Add `test_pending_reservation_cannot_be_stolen_before_submit`: pause the first caller after reservation but before submit, require the second same-role call to return `busy`, and assert the Supervisor receives one submit only.

Add a real Supervisor race test that holds the service lease lock while a Worker finalizes. Assert `get`, `list`, and `wait` remain responsive before releasing the lease lock, and assert observer delivery, runtime cleanup, and a later same-role dispatch complete afterward without deadlock.

Add one table-driven batch test with ordered entries for role, capability, missing route, unknown route, blank prompt, invalid timeout, non-mapping input, non-string truthy route, ignored extra fields, and per-item Worker infrastructure failure. Assert the result count and position never change and dispatch calls occur sequentially.

- [ ] **Step 2: Run the new module and verify RED.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_dispatch_service -v
```

Expected: ERROR because `core.brain.role_dispatch_service` does not exist.

- [ ] **Step 3: Implement service errors, leases, terminal mapping, and batch rules.**

Use these public constants and signatures:

```python
ROLE_WORKER_UNAVAILABLE = "Role worker is unavailable"
ROLE_TASK_TERMINATION_UNCONFIRMED = "Worker process termination is not confirmed"
ROLE_WORKER_INVALID_RESULT = "Role worker returned an invalid result"

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
```

Generate `WorkerTaskRequest` before reserving. Under `_lease_lock`, reconcile an existing task through `supervisor.get`: an ID in `_pending_submissions` is always busy; otherwise remove only a missing record or a confirmed terminal record. Reserve by writing both `_leases[role] = task_id` and `_pending_submissions.add(task_id)` atomically. A conflict returns `DispatchResult(role, new_id, "busy", f"Agent '{role}' is busy")`. Release the lock before submit or wait. After submit succeeds, discard the pending marker. On submit failure, inspect `supervisor.get(new_id)`, discard the marker, and compare-and-remove the lease only when no record exists; otherwise retain fail-closed. Raise `RoleWorkerUnavailableError(role, task_id, ROLE_WORKER_UNAVAILABLE)`. Wait with `supervisor.wait(task_id, supervisor.terminal_wait_budget(request.timeout_seconds))`, so monitor and termination policy remain Supervisor-owned. A missing result is an invalid Worker result; a nonterminal or unconfirmed result raises `RoleTaskTerminationUnconfirmedError(role, task_id, ROLE_TASK_TERMINATION_UNCONFIRMED)` without releasing the lease. The terminal observer discards any matching pending marker and compare-and-removes only a confirmed terminal lease.

For `SUCCEEDED`, require `record.result` and `record.result["dispatch"]` to be mappings, require the exact key set `{role_name, task_id, status, message}`, require all four values to be strings, and require the inner role to equal the selected role. Return its role/status/message with `record.task_id`. Map confirmed `TIMEOUT` to `DispatchResult(role, outer_id, "timeout", "Role task timed out")`; map `FAILED`, `CRASHED`, and `CANCELLED` to status `error` with stable redacted generic text. Never record token usage here.

For batch, treat a truthy `role` as role routing only when it is a string; otherwise produce a positional error. When `role` is absent or false, apply the same truthy rule to `capability`. When both are absent or false, choose `registry.list_roles()[0]`. Require `prompt` to be a string and `timeout` to be a strict integer in `1..300`; blank prompt is converted to a positional error because `WorkerTaskRequest` rejects it. Ignore extra fields. Catch service exceptions per item and continue.

- [ ] **Step 4: Run the service and Supervisor race suites.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_role_dispatch_service tests.test_role_worker -v
```

Expected: all tests pass; no service method holds `_lease_lock` while submitting or waiting.

- [ ] **Step 5: Commit the compatibility service.**

```powershell
git add src/core/brain/role_dispatch_service.py tests/test_role_dispatch_service.py
git commit -m "feat: bridge synchronous role dispatch to workers"
```

---

### Task 4: FastAPI Compatibility Adapter

**Files:**
- Modify: `src/main_fastapi.py:58-67,195-213,316-347,1111-1197`
- Modify: `tests/test_main_fastapi.py:194-571`

**Interfaces:**
- Consumes: one shared `RoleWorkerSupervisor` and `RoleDispatchService` in `AppState`.
- Produces: complete `AppState.shutdown()` with Worker-first idempotent cleanup.
- Produces: stable HTTP `503` envelopes for all three service exception types.
- Guarantees: the entire synchronous submit-and-wait call runs in `asyncio.to_thread`.

- [ ] **Step 1: Write deterministic injected-adapter tests.**

Extend the isolated state fixture with fake role dispatch and role task services. Replace old environment-dependent `[200, 500, 502]` assertions with exact tests for argument forwarding and the unchanged four-field response. Verify unknown role/capability results returned by the service become the existing `404`; the adapter must call the service once and must not pre-resolve roles itself. Parameterize the three service exceptions to require `ROLE_WORKER_UNAVAILABLE`, `ROLE_TASK_TERMINATION_UNCONFIRMED`, and `ROLE_WORKER_INVALID_RESULT` with status `503`.

For each of the three routes, block a fake service call on a threading event, issue it in one client thread, and prove `/api/health` completes before releasing the event. Verify isolated lifespan shutdown calls the shared Supervisor exactly once and before orchestrator/factory/terminal resources.

- [ ] **Step 2: Run the adapter tests and verify RED.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main_fastapi -v
```

Expected: new assertions fail because synchronous methods call `state.agent_factory` on the event-loop thread and `AppState` has no role dispatch service.

- [ ] **Step 3: Compose the service and migrate all three routes.**

Add `role_dispatch: RoleDispatchService | None = None` to `AppState`. When absent, build it from `self.role_registry` and the same `self.role_tasks`; when injected, do not construct another Supervisor. Route calls have this exact async boundary:

```python
try:
    result = await asyncio.to_thread(
        state.role_dispatch.dispatch_by_role,
        role_name,
        prompt,
        timeout,
    )
except RoleWorkerUnavailableError:
    raise _role_dispatch_http_error(
        "ROLE_WORKER_UNAVAILABLE",
        "Role worker is unavailable",
    ) from None
except RoleTaskTerminationUnconfirmedError:
    raise _role_dispatch_http_error(
        "ROLE_TASK_TERMINATION_UNCONFIRMED",
        "Worker process termination is not confirmed",
    ) from None
except RoleWorkerInvalidResultError:
    raise _role_dispatch_http_error(
        "ROLE_WORKER_INVALID_RESULT",
        "Role worker returned an invalid result",
    ) from None
```

Use the corresponding capability method and `await asyncio.to_thread(state.role_dispatch.batch_dispatch, tasks)`. Keep adapter syntax validation unchanged, but remove adapter registry prechecks; map returned `no_role` and `no_capability` results to the existing 404 envelopes so role selection remains owned by the service. Make lifespan call `app_state.shutdown()`, with idempotent Worker-first cleanup.

- [ ] **Step 4: Run FastAPI and shared service regressions.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main_fastapi tests.test_role_dispatch_service -v
```

Expected: all tests pass and health remains responsive during each compatibility wait.

- [ ] **Step 5: Commit the FastAPI migration.**

```powershell
git add src/main_fastapi.py tests/test_main_fastapi.py
git commit -m "feat: migrate fastapi role dispatch to workers"
```

---

### Task 5: Standard-Library HTTP Adapter and Complete Lifecycle

**Files:**
- Modify: `src/main.py:64-156,918-1010`
- Modify: `tests/test_main.py:1160-1290`

**Interfaces:**
- Produces: `AppState(..., role_tasks=None, role_dispatch=None)` using one shared Supervisor.
- Produces: `create_http_server(host, port, app_state=None)` with a bound handler subclass for injected state.
- Produces: `run_server(host=None, port=8080, app_state=None)`.
- Guarantees: existing bare-handler tests retain the class-level default state, while real servers can bind an isolated state without mutating globals.

- [ ] **Step 1: Write injected HTTP and lifecycle tests.**

Create `TestMainHTTPRoleDispatchWorkerAdapter` and `TestMainHTTPStateLifecycle`. Start `create_http_server(..., app_state=fake_state)` and verify role/capability/batch forwarding, unchanged success shapes and 404s, exact three-way `503` mapping, and positional batch errors. Unknown role/capability must be returned by the service and mapped after the call. Assert `AgentFactory` compatibility methods are never called. Verify `AppState.shutdown()` is idempotent and orders Worker, orchestrator, factory, terminal; verify `run_server` executes that cleanup from `finally` without mutating module state.

- [ ] **Step 2: Run those classes and verify RED.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main.TestMainHTTPRoleDispatchWorkerAdapter tests.test_main.TestMainHTTPStateLifecycle -v
```

Expected: FAIL because handlers use global `state`, no HTTPServer state seam exists, and shutdown closes only the terminal.

- [ ] **Step 3: Migrate composition, handlers, and shutdown.**

Build `RoleWorkerSupervisor(execute_role_task, runner_config=..., on_terminal=...)` exactly as FastAPI does, then build `RoleDispatchService` from it. Add one exception-to-envelope helper used by both single routes. Batch always serializes service results as `200 {"results": [...], "count": len(results)}`.

Give `JARVISHandler` a class attribute `app_state = state`, replace request-time `state.*` access with `self.app_state.*`, and bind injected state without breaking `object.__new__(JARVISHandler)` tests:

```python
def create_http_server(host: str, port: int, app_state: AppState | None = None):
    handler_type = JARVISHandler
    if app_state is not None:
        handler_type = type(
            "BoundJARVISHandler",
            (JARVISHandler,),
            {"app_state": app_state},
        )
    return _IPv4HTTPServer((host, port), handler_type)
```

Register `state.shutdown` with `atexit`; do not register `terminal.close` separately. In `run_server`, use `active_state = app_state or state`, create the server through `create_http_server`, and call `active_state.shutdown()` once from `finally` after closing the server.

- [ ] **Step 4: Run standard HTTP, FastAPI, and service regressions.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main tests.test_main_fastapi tests.test_role_dispatch_service -v
```

Expected: all tests pass and no test-owned Worker remains alive.

- [ ] **Step 5: Commit the HTTPServer migration.**

```powershell
git add src/main.py tests/test_main.py
git commit -m "feat: migrate http role dispatch to workers"
```

---

### Task 6: Express Budget and OpenAPI 1.13 Contract

**Files:**
- Modify: `frontend/server/core-api.js:5-29`
- Modify: `frontend/server/core-api.test.js`
- Modify: `frontend/server.js:343-359,667-711`
- Modify: `frontend/server.test.js:587-716`
- Modify: `contracts/core-api.openapi.json:5,1079-1351`
- Modify: `tests/test_api_contract.py:410-412,986-1350`

**Interfaces:**
- Produces: `coreApi.request(path, init, {timeoutMs} = {})`, falling back to the existing client default for all other routes.
- Produces: a synchronous role proxy budget derived from validated timeout values and fixed grace; batch uses the sum of valid item budgets.
- Declares: OpenAPI version exactly `1.13.0` and terminable-Worker descriptions only on the three synchronous role paths.

- [ ] **Step 1: Write failing proxy and contract tests.**

In `core-api.test.js`, use fake timers to prove a per-request timeout override can exceed the default and is not forwarded as a fetch option. In `server.test.js`, delay a Core role response beyond 3 seconds under fake timers and require it to pass through; parameterize all three Worker `503` envelopes and require byte-equivalent JSON/status forwarding; retain batch `200` positional errors.

In `test_api_contract.py`, require `1.13.0`; require all three operation descriptions to say execution uses a terminable Worker; require the two single-dispatch `503` descriptions to name unavailable, invalid-result, and unconfirmed-termination cases; require the batch `503` description to remain limited to Core/BFF configuration or proxy failure and explicitly state Worker item failures remain positional results under `200`; and assert `/api/orchestrator/dispatch` does not claim terminable execution.

- [ ] **Step 2: Run proxy and contract tests and verify RED.**

```powershell
Set-Location frontend
.\node_modules\.bin\vitest.cmd run server/core-api.test.js server.test.js
Set-Location ..
.\venv\Scripts\python.exe -m unittest tests.test_api_contract -v
```

Expected: FAIL because Core requests have a fixed 3000 ms budget and the contract is still `1.12.0`.

- [ ] **Step 3: Add bounded role-specific proxy budgets and update the contract.**

Keep the default for all other requests, but implement this request override:

```javascript
async function request(path, init = {}, { timeoutMs: requestTimeoutMs } = {}) {
  const effectiveTimeoutMs = requestTimeoutMs ?? timeoutMs;
  if (!normalizedBaseUrl) {
    throw coreError('CORE_API_NOT_CONFIGURED', 'Core API is not configured');
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), effectiveTimeoutMs);
  let response;
  try {
    response = await fetchImpl(`${normalizedBaseUrl}${path}`, {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    throw coreError('CORE_API_UNAVAILABLE', 'Core API is unavailable', error);
  } finally {
    clearTimeout(timeout);
  }
  try {
    return { status: response.status, body: await response.json() };
  } catch (error) {
    throw coreError(
      'CORE_API_INVALID_RESPONSE',
      'Core API returned invalid JSON',
      error,
    );
  }
}
```

Extend `proxyCoreRequest(req, res, capability, options)` to pass `options` to `coreApi.request`. For role and capability routes use `timeout * 1000 + 5000`. For batch, sum `timeout * 1000 + 5000` for every mapping item with a strict valid timeout, use the default 300 seconds for omitted/invalid values because Core converts invalid entries to positional errors, and cap the JavaScript timer at `2_147_483_647` ms. Do not alter response bodies or remap Core Worker errors.

Set `info.version` to `1.13.0`, preserve request and `200` schemas, and extend only the three path descriptions and `503` descriptions with the batch distinction above. In the real three-adapter harness, inject an `OllamaManager(base_url=fixture_url)` before either Python `AppState` is constructed, use `create_http_server(..., app_state=http_state)`, dispatch the same role request through Python HTTP, Express, and FastAPI, and assert success/message/four-field shape plus a nonempty outer task ID. Explicitly shut down both Python states.

- [ ] **Step 4: Run contract, proxy, and required-services integration tests.**

```powershell
Set-Location frontend
.\node_modules\.bin\vitest.cmd run server/core-api.test.js server.test.js
Set-Location ..
.\venv\Scripts\python.exe -m unittest tests.test_api_contract -v
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services --timeout 15
```

Expected: all commands pass; all adapters return the same existing shape through the fixed Worker, and Express no longer aborts at three seconds.

- [ ] **Step 5: Commit proxy and OpenAPI changes together.**

```powershell
git add frontend/server/core-api.js frontend/server/core-api.test.js frontend/server.js frontend/server.test.js contracts/core-api.openapi.json tests/test_api_contract.py
git commit -m "feat: declare terminable synchronous role dispatch"
```

---

### Task 7: Aggregate Gates and Iteration 132 Evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_132.md`
- Delete: `docs/reports/AUDIT_REPORT_122.md`

**Interfaces:**
- Registers: the new service and adapter regression classes in the canonical aggregate suite and its coverage guard.
- Records: only test counts measured after the final code is present.
- Preserves: persistent task recovery and model tool loops as the next Phase 11 work.

- [ ] **Step 1: Make aggregate coverage fail for the new tests.**

Update `tests/test_run_all_coverage.py` to require `tests.test_role_dispatch_service` and the new HTTP/FastAPI adapter classes before adding them to `tests/run_all.py`. Change the aggregate title and docstring from Iteration 131 to 132.

- [ ] **Step 2: Run the coverage guard and verify RED, then register the tests.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_run_all_coverage -v
```

Expected before registration: FAIL naming the missing module/classes. Add exact imports and `loader.loadTestsFromTestCase(...)` entries, rerun, and expect PASS.

- [ ] **Step 3: Run every delivery gate and capture literal output.**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory tests.test_role_worker tests.test_role_dispatch_service tests.test_main tests.test_main_fastapi tests.test_api_contract -v
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe scripts/ci_local_integration.py --require-services --timeout 15
Set-Location frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
git diff --check
```

Expected: every command exits `0`; Playwright may retain its documented desktop-only conditional skip. If Ruff is installed, also run `.\venv\Scripts\python.exe -m ruff check src tests scripts`; otherwise record that the optional tool is unavailable.

- [ ] **Step 4: Update current-state documentation from measured evidence.**

Create `AUDIT_REPORT_132.md` with commit IDs, exact aggregate/discovery/frontend counts, fixed route evidence, and remaining Phase 11 work. Delete only the rolling historical `AUDIT_REPORT_122.md`, update report navigation to Iterations 123-132, and update current iteration/baseline text in the listed documents. State explicitly that generic orchestrator dispatch is unchanged and task persistence/model tool loops remain pending.

Run this stale-current-state scan and review matches in historical reports or old changelog entries rather than rewriting history:

```powershell
rg -n "Iteration 131|1\.12\.0|old synchronous|122-131" AGENTS.md README.md CHANGELOG.md docs contracts tests/run_all.py
```

- [ ] **Step 5: Review scope and create the Iteration 132 evidence commit.**

```powershell
git status --short
git diff --stat HEAD
git diff --check
git add tests/run_all.py tests/test_run_all_coverage.py README.md AGENTS.md CHANGELOG.md docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_132.md docs/reports/AUDIT_REPORT_122.md
git commit -m "chore: finalize iteration 132 verification ledger"
```

Expected: `RISK_COMPONENTS.log` remains the only unrelated unstaged change. Do not mark the project goal complete; Iteration 133 will begin with persistent role-task recovery.

---

## Self-Review Record

- Spec coverage: every goal, non-goal, lifecycle rule, result mapping, batch compatibility branch, adapter boundary, proxy budget, OpenAPI change, and acceptance criterion maps to Tasks 1-7.
- Placeholder scan: every implementation and verification step names concrete behavior, files, commands, and expected outcomes.
- Type consistency: `execute_role_once` always requires keyword `task_id`; service methods return `DispatchResult`; Supervisor `wait` returns a record or `None`; adapter exception names and OpenAPI codes are identical across tasks.
- Lock consistency: Supervisor observers never run under a Supervisor lock; active waiters block pruning; the service never holds `_lease_lock` while calling Supervisor `submit` or `wait`; pending reservations cannot be mistaken for pruned records; pruning occurs only after confirmed terminal publication and observer delivery.
- Deadline consistency: child Ollama uses `timeout=None`, direct role execution has no Orchestrator deadline, Core Supervisor owns execution timeout, and Express only supplies a longer transport budget.
