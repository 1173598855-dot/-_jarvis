# Generic Orchestrator Timeout Quarantine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a timed-out in-process generic orchestrator handler from being re-used or unregistered until its daemon thread has actually exited, while preserving the existing public dispatch contract.

**Architecture:** Keep the existing stdlib thread runtime and response shapes. A private timeout exception carries the still-live thread into `_RegisteredAgent`; its lock-protected quarantine state blocks assignment, retry reset, and removal until a state observation confirms natural thread exit.

**Tech Stack:** Python 3.10+, `threading`, `unittest`, existing `Orchestrator` API.

## Global Constraints

- Preserve `AgentResult`, `AgentInfo`, HTTP adapter, Express bridge, and OpenAPI response shapes.
- Do not kill Python threads, serialize arbitrary handlers, add a dependency, or migrate generic dispatch to a process Worker in this increment.
- A `thread.join()` timeout is quarantined; a `TimeoutError` raised by a completed handler remains non-recoverable through `recover_agent()`, while existing `dispatch_with_retry()` reset behavior continues to retry it.
- A late handler result must not alter the already recorded timeout result or history.
- Production behavior changes follow a red-green test cycle.

---

### Task 1: Prove the unsafe timeout lifecycle

**Files:**
- Modify: `tests/test_orchestrator_extended_v2.py`

**Interfaces:**
- Consumes: `Orchestrator.register()`, `dispatch()`, `dispatch_with_retry()`, and `unregister()`.
- Produces: deterministic regressions for no unregister, re-register, or reuse before a timed-out handler exits, plus a registry-race guard.

- [ ] **Step 1: Write the failing tests**

Add `TestOrchestratorTimeoutQuarantine` with a `threading.Event`-blocked handler. Dispatch `AgentTask("first", "worker", "first", timeout=0.01)` and assert:

```python
self.assertEqual(first.status, "timeout")
self.assertFalse(orch.unregister("worker"))
self.assertEqual(
    orch.dispatch(AgentTask("second", "worker", "second", timeout=1)).status,
    "busy",
)
self.assertEqual(calls, ["first"])
```

Release the event, wait for the handler's `finished` event, then dispatch a third task and assert success with `calls == ["first", "third"]`. Add a re-registration case that calls `register("worker", replacement)` during quarantine and still receives `busy`, then permits replacement after exit. In a second test, invoke `dispatch_with_retry(..., max_retries=2, backoff_factor=0)` against a blocked timed-out handler and assert its result stays `timeout` and the handler call list remains `["first"]`. Add a controlled `can_unregister` event hook: while unregister has entered its decision, concurrent dispatch must not start the handler and must return `not found` after successful removal. Use `finally` blocks to release every event and join test threads.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended_v2 -v
```

Expected: `unregister("worker")` returns `True` in the old state machine and the retry path starts additional handler calls.

### Task 2: Add lock-protected timeout quarantine

**Files:**
- Modify: `src/core/brain/orchestrator.py`
- Test: `tests/test_orchestrator_extended_v2.py`

**Interfaces:**
- Consumes: `_RegisteredAgent.try_assign(task) -> bool`, `_RegisteredAgent.quarantine(thread) -> None`, `_RegisteredAgent.has_pending_execution() -> bool`, `_RegisteredAgent.can_unregister() -> bool`, `_AgentExecutionTimeout.thread`, and `Orchestrator._agents_lock`.
- Produces: an agent that cannot be reassigned or unregistered while its timed-out thread is alive and becomes `IDLE` after observed exit.

- [ ] **Step 1: Distinguish join timeout from handler timeout**

Add this private exception near the logger and raise it only when the thread is still alive after `join()`:

```python
class _AgentExecutionTimeout(TimeoutError):
    def __init__(self, thread: threading.Thread, timeout: int) -> None:
        super().__init__(f"Handler exceeded {timeout}s timeout")
        self.thread = thread
```

- [ ] **Step 2: Add agent lifecycle methods**

Track `self._pending_thread: Optional[threading.Thread] = None`. Under the existing lock, reap it only when it is no longer alive, then clear `current_task`, `_pending_thread`, `_error_recoverable`, and return the agent to `IDLE` unless its state is `SHUTDOWN`. Implement `try_assign`, `quarantine`, `has_pending_execution`, `can_unregister`, and `shutdown`; make `is_available`, `reset`, `recover_from_error`, and `info` reap first. `reset` must leave a still-pending execution untouched.

- [ ] **Step 3: Wire the state machine**

Add `_agents_lock` to protect registry lookup and membership. Within that lock, make `register()` reject replacement of active agents, make `unregister()` use `can_unregister()` before deletion, and make `dispatch()` look up plus `try_assign(task)` atomically. Snapshot registry members during shutdown, then set each Agent to `SHUTDOWN`. Catch `_AgentExecutionTimeout` before `TimeoutError`, quarantine the carried thread, and retain the existing `timeout` result/message/statistics. Keep a separate ordinary `TimeoutError` branch that calls `agent.fail(recoverable=False)` so `recover_agent()` keeps its existing contract. In `dispatch_with_retry()`, read/reset and pending-execution checks through `_agents_lock`; return the original timeout immediately when the current agent reports a pending execution, otherwise preserve the current reset/backoff behavior.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v
```

Expected: all lifecycle/retry tests pass, including existing handler-raised `TimeoutError` recovery coverage.

### Task 3: Audit, evidence, and checkpoint

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_144.md`
- Delete: `docs/reports/AUDIT_REPORT_134.md`

**Interfaces:**
- Consumes: verified test totals and the rolling report policy.
- Produces: Iteration 144 evidence that distinguishes in-process timeout quarantine from a process Worker migration.

- [ ] **Step 1: Self-review behavior and diff**

Confirm that no endpoint, schema, request validation, response field, Plugin authority, or role Worker behavior changed; confirm that a late handler only restores availability and never writes a second result.

- [ ] **Step 2: Run required verification**

```powershell
.\venv\Scripts\python.exe tests\run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
cd frontend; npm test -- --run
cd frontend; npm run test:e2e
cd frontend; npm run typecheck
cd frontend; npm run build
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
git diff --check
```

- [ ] **Step 3: Synchronize the ledger**

Record actual verification totals in Iteration 144. State that generic dispatch remains in-process but a timed-out handler cannot be re-used or unregistered until it exits. Keep full Worker migration as P1. Update report navigation to 135-144 and remove only `AUDIT_REPORT_134.md`.

- [ ] **Step 4: Create a local commit**

Run `git status --short`, `git diff --check`, and a staged secret scan, then commit only the files changed by this plan with:

```powershell
git commit -m "fix(orchestrator): quarantine timed-out handlers"
```
