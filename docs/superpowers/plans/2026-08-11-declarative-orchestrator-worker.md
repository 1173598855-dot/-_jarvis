# Declarative Orchestrator Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, statically declared generic Orchestrator Worker path with confirmed timeout termination while preserving arbitrary callable compatibility.

**Architecture:** A new `orchestrator_worker` adapter serializes `AgentTask` data into the existing `WorkerTaskRequest` transport and resolves only audited module-local runner IDs in the child. `Orchestrator` keeps a per-Agent supervisor reference, maps confirmed Worker records back to `AgentResult`, and quarantines any unconfirmed process before reuse.

**Tech Stack:** Python 3.10+, `multiprocessing` spawn, `threading`, existing `RoleWorkerSupervisor`, existing `WorkerTaskRequest`, `unittest`.

## Global Constraints

- Preserve `AgentResult`, `AgentInfo`, HTTP adapter routes, Express bridge, and OpenAPI response schemas.
- Keep `Orchestrator.register(name, callable, ...)` as the in-process compatibility path.
- Declared runners must be static module-local identifiers; do not accept module paths, commands, paths, environments, tokens, or dynamic imports.
- Serialize only bounded JSON task metadata using exact built-in JSON values; invalid values and hostile subclasses fail closed before Worker start.
- Timeout/cancel lifecycle is terminal only after the existing supervisor confirms child termination.
- Production behavior changes follow a red-green test cycle.

---

### Task 1: Specify the declared-worker behavior with failing tests

**Files:**
- Modify: `tests/test_orchestrator_extended_v2.py`
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Consumes: `Orchestrator.register_declared(name, runner_id, capabilities=None)`, `dispatch()`, `dispatch_with_retry()`, `recover_agent()`, and the legacy `register()` API.
- Produces: deterministic child-process success, static-runner rejection, serialization failure, timeout-confirmation, and legacy-compatibility regressions.

- [x] **Step 1: Write the failing tests**

```python
orch = Orchestrator()
orch.register_declared("worker", "echo", capabilities=["analysis"])
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
self.assertEqual(result.status, "success")
self.assertEqual(result.result["prompt"], "inspect")
self.assertNotEqual(result.result["worker_pid"], os.getpid())
```

Add an unknown-runner assertion, a non-JSON metadata assertion, a delayed
`metadata={"delay_ms": 1100}` timeout assertion, and a legacy handler that
returns `os.getpid()` to prove it remains parent-process compatibility.

- [x] **Step 2: Verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended_v2 -v
```

Expected: `AttributeError` because `register_declared` does not exist.

### Task 2: Implement the static runner adapter

**Files:**
- Create: `src/core/brain/orchestrator_worker.py`
- Test: `tests/test_orchestrator_extended_v2.py`

**Interfaces:**
- Consumes: `RoleWorkerSupervisor`, `WorkerTaskRequest`, `WorkerTaskRecord`, and canonical JSON task fields.
- Produces: `DeclaredAgentWorker`, `execute_declared_agent_task()`, `is_known_runner()`, and the static `echo` runner.

- [x] **Step 1: Encode and validate full task data**

```python
payload = {
    "task_id": task_id,
    "agent_name": agent_name,
    "prompt": prompt,
    "timeout": timeout,
    "priority": priority,
    "metadata": metadata,
}
encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
```

Reject malformed names, non-plain or unknown runner IDs, out-of-range plain
integer timeout/priority values, non-plain-dict metadata, over-limit payloads,
and non-JSON values before calling `RoleWorkerSupervisor.submit()`.

- [x] **Step 2: Resolve only the trusted static runner in the child**

```python
runner = _DECLARED_RUNNERS[runner_id]
return runner(task_payload)
```

`execute_declared_agent_task()` reconstructs a strict payload from the Worker
request and verifies the agent and timeout agree with its trusted envelope.
The `echo` runner optionally sleeps for a bounded `metadata.delay_ms`, then
returns the task projection and `os.getpid()`.

- [x] **Step 3: Preserve process confirmation observability**

Expose `dispatch(...) -> WorkerTaskRecord | None`, `has_pending_execution()`,
and `shutdown()` on `DeclaredAgentWorker`. Do not clear the active worker ID
until its record is terminal and `termination_confirmed` is true.

- [x] **Step 4: Verify focused adapter behavior**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended_v2 -v
```

Expected: declared-worker tests still fail only until `Orchestrator` consumes
the adapter; the static runner's direct boundaries are covered by the same
suite after Task 3.

### Task 3: Integrate declared Workers into Orchestrator lifecycle

**Files:**
- Modify: `src/core/brain/orchestrator.py`
- Test: `tests/test_orchestrator_extended_v2.py`

**Interfaces:**
- Consumes: `DeclaredAgentWorker.dispatch()`, `has_pending_execution()`, `shutdown()`, and `WorkerTaskStatus`.
- Produces: `Orchestrator.register_declared()` and unchanged `AgentResult`/`AgentInfo` response shapes.

- [x] **Step 1: Add an optional declared-worker field to `_RegisteredAgent`**

Keep normal handlers unchanged. Teach reaping, availability, removal, retry,
and shutdown to consult a pending declared Worker before reopening the Agent.

- [x] **Step 2: Register declared Agents atomically**

Validate the runner before changing `_agents`. Preserve the existing behavior
that a live Agent cannot be replaced or removed.

- [x] **Step 3: Map confirmed records back to generic results**

Map success, timeout, and other terminal statuses to the existing generic
result strings and counters. A nonterminal or unconfirmed record must return
`timeout`, retain the pending Worker reference, and prevent reuse until a
later state observation reaps it. If a post-submit transport or Supervisor
exception occurs while the Worker still reports active, preserve the same
fail-closed quarantine rather than exposing a recoverable Agent error.

- [x] **Step 4: Verify GREEN**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v
```

Expected: all legacy and declared Worker lifecycle tests pass.

### Task 4: Audit, evidence, and checkpoint

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_145.md`
- Delete: `docs/reports/AUDIT_REPORT_135.md`

**Interfaces:**
- Consumes: actual test totals, rolling report policy, and stable API contract.
- Produces: accurate Iteration 145 evidence distinguishing declared Worker isolation from callable compatibility.

- [x] **Step 1: Self-review state and scope**

Confirm that arbitrary callable behavior, endpoint schemas, API validation,
Plugin authority, role Worker behavior, and data persistence are unchanged.
Confirm that a declared Worker result is recorded once and that an
unconfirmed process cannot be re-dispatched, removed, or replaced.

- [x] **Step 2: Run required verification**

```powershell
.\venv\Scripts\python.exe tests\run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
cd frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
..\venv\Scripts\python.exe ..\scripts\ci_local_integration.py --require-services
git diff --check
```

- [x] **Step 3: Synchronize the ledger and commit**

Record real totals and outstanding limits: only static declared runners are
terminable; arbitrary callables retain the quarantined daemon-thread path.
Keep exactly reports 136-145, then commit the explicit changed files with:

```powershell
git add src/core/brain/orchestrator.py src/core/brain/orchestrator_worker.py tests/test_orchestrator_extended_v2.py tests/run_all.py tests/test_run_all_coverage.py README.md AGENTS.md CHANGELOG.md docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_145.md docs/reports/AUDIT_REPORT_135.md docs/superpowers/specs/2026-08-11-declarative-orchestrator-worker-design.md docs/superpowers/plans/2026-08-11-declarative-orchestrator-worker.md
git commit -m "feat(orchestrator): add declared worker dispatch"
```
