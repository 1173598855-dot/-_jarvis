# Importable Callable Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an internal process-backed registration path for stable top-level callables, with parent-owned history and confirmed timeout/cancellation lifecycle.

**Architecture:** `register_worker()` derives and validates a module/function locator from a callable object, then creates an `ImportableAgentWorker` that reuses `RoleWorkerSupervisor`. The child reconstructs the bounded JSON task and invokes the imported function; the parent maps the confirmed Worker record to the existing `AgentResult` contract and exposes a narrow synchronous cancellation method.

**Tech Stack:** Python 3.10+, `multiprocessing` spawn, existing `RoleWorkerSupervisor`, `WorkerTaskRequest`, `unittest`.

## Global Constraints

- Preserve `register()` as the arbitrary in-process compatibility path.
- Accept only exact module-level Python functions; reject lambdas, nested functions, bound methods, callable instances, and `__main__` before registry mutation.
- Do not accept caller-supplied module names, commands, paths, environments, or capability tokens.
- Reuse bounded JSON task validation and the existing confirmed Worker termination protocol.
- Keep all registration and cancellation APIs internal; do not change HTTP/OpenAPI surfaces.

---

### Task 1: Add failing fixture and regression tests

**Files:**
- Create: `tests/orchestrator_worker_fixtures.py`
- Modify: `tests/test_orchestrator_extended_v2.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Consumes: the planned `Orchestrator.register_worker()` and `Orchestrator.cancel()` signatures.
- Produces: red tests for child execution, invalid callable rejection, AgentResult mapping, timeout, cancellation, and single parent history ownership.

- [x] **Step 1: Add module-level fixtures**

```python
def project_task(task):
    return {"pid": os.getpid(), "task_id": task.task_id, "prompt": task.prompt}

def delayed_task(task):
    time.sleep(float(task.metadata.get("delay", 0)))
    return project_task(task)

def result_task(task):
    from core.brain.orchestrator import AgentResult
    return AgentResult(task.task_id, task.agent_name, result="wrapped", status="success")
```

- [x] **Step 2: Add one test for child execution and result mapping**

```python
orch = Orchestrator()
orch.register_worker("worker", fixtures.project_task)
result = orch.dispatch(AgentTask("task", "worker", "inspect", timeout=1))
self.assertEqual(result.status, "success")
self.assertNotEqual(result.result["pid"], os.getpid())
```

- [x] **Step 3: Add rejection, timeout, and cancellation tests**

Assert that lambda/nested/bound/`__main__` functions raise `ValueError` with an
empty registry; a delayed task returns confirmed `timeout`; and a background
dispatch cancelled with `orch.cancel("worker", "cancel-task")` returns
`cancelled`, leaves one history entry, and leaves the Worker process count at
zero.

- [x] **Step 4: Run the focused tests and verify RED**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended_v2 -v`

Expected: the new tests fail with missing `register_worker`/`cancel` APIs while
the existing Iteration 145 tests continue to pass.

### Task 2: Implement callable locator and child runner

**Files:**
- Modify: `src/core/brain/orchestrator_worker.py`
- Test: `tests/test_orchestrator_extended_v2.py`

**Interfaces:**
- Consumes: `AgentTask`, `AgentResult`, `RoleWorkerSupervisor`, and the existing bounded task encoder.
- Produces: `ImportableAgentWorker`, `execute_importable_agent_task()`, and callable locator validation.

- [x] **Step 1: Validate a top-level function locator before process creation**

Require `types.FunctionType`, non-`__main__` `__module__`, a single top-level
`__qualname__`, and an exact module binding. Return a fixed
`{"module_name": ..., "function_name": ...}` mapping; never accept a locator
string from the caller.

- [x] **Step 2: Add the child entry point and result envelope**

Import the validated module, resolve the function, reconstruct `AgentTask`
from `_decode_task()`, invoke it, and return either
`{"kind":"value","value":...}` or
`{"kind":"agent_result","value": result.to_dict()}`.

- [x] **Step 3: Reuse Worker lifecycle and add cancellation to the worker**

Track both the internal Worker task ID and caller task ID, keep ownership until
confirmed terminal state, and add `cancel(caller_task_id)` returning the
confirmed `WorkerTaskRecord` or `None`.

- [x] **Step 4: Run focused tests and verify GREEN for adapter behavior**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended_v2 -v`

Expected: adapter and direct child tests pass; Orchestrator integration tests
remain red until Task 3.

### Task 3: Integrate registration, mapping, and cancellation

**Files:**
- Modify: `src/core/brain/orchestrator.py`
- Test: `tests/test_orchestrator_extended_v2.py`

**Interfaces:**
- Consumes: `ImportableAgentWorker`, `decode_result()`, and confirmed cancellation records.
- Produces: `register_worker(name, handler, capabilities=None)`, `cancel(agent_name, task_id)`, and unchanged public result fields.

- [x] **Step 1: Add atomic registration**

Construct and validate the candidate Worker before replacing the registry; shut
it down if a live Agent prevents replacement. Keep the existing declared and
legacy registration semantics unchanged.

- [x] **Step 2: Map Worker success and cancellation**

Decode the result envelope, preserve returned `AgentResult` values, map
confirmed cancellation to `status="cancelled"` with no counter increment, and
record history only in the parent dispatch path.

- [x] **Step 3: Expose narrow synchronous cancellation**

Find the matching Worker-backed Agent, request cancellation outside the global
registry lock, and return `True` only for a confirmed `CANCELLED` record.

- [x] **Step 4: Run all orchestrator tests**

Run: `\.venv\Scripts\python.exe -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v`

Expected: all tests pass with exactly one history entry for a cancelled task.

### Task 4: Self-review, evidence, and documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_146.md`
- Delete: `docs/reports/AUDIT_REPORT_136.md`

**Interfaces:**
- Consumes: actual verification counts and the current rolling-report policy.
- Produces: accurate Iteration 146 evidence distinguishing importable-function Worker isolation from legacy callable compatibility.

- [x] **Step 1: Review the diff and boundary cases**

Check that no HTTP/OpenAPI route, Plugin authority, role Worker, or unrelated
user change moved; check history is recorded once and unconfirmed Workers stay
quarantined.

- [x] **Step 2: Run required verification**

Run the focused orchestrator suite, aggregate Python suite, full discovery,
compileall, frontend Vitest/Playwright/typecheck/build, CI local integration,
`python -m ruff check src tests scripts`, and `git diff --check`.

- [x] **Step 3: Update rolling evidence with actual counts**

Record the fresh command outputs, preserve the known lint backlog if unchanged,
and state explicitly that only stable top-level functions receive the new
process path while closures remain on legacy compatibility.
