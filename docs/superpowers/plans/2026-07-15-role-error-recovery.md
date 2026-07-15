# Role Error Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover a role for a later request after its completed handler raises, without retrying the failed request or weakening timeout safety.

**Architecture:** Mark internal error states as recoverable or nonrecoverable, add an atomic recoverable `ERROR -> IDLE` transition to `_RegisteredAgent`, and expose it through `Orchestrator.recover_agent(name)`. `AgentFactory` invokes that public boundary only after an ordinary `error` result; timeout, busy, idle, shutdown, and missing-agent states remain unchanged.

**Tech Stack:** Python 3 standard library, `unittest`, existing role registry and orchestrator.

## Global Constraints

- Do not add dependencies or change public HTTP route shapes.
- Preserve the failed result, history entry, error counters, and dispatch statistics.
- Do not retry a failed role request automatically.
- Do not recover `timeout`; its daemon handler thread may still be running.
- Preserve unrelated worktree changes and stage only files owned by the task.

---

### Task 1: Atomic Orchestrator Recovery Boundary

**Files:**
- Modify: `tests/test_orchestrator_extended.py`
- Modify: `src/core/brain/orchestrator.py`

**Interfaces:**
- Produces: `_RegisteredAgent.recover_from_error() -> bool`.
- Produces: `_RegisteredAgent.fail(*, recoverable: bool = True) -> None`.
- Produces: `Orchestrator.recover_agent(name: str) -> bool`.

- [ ] **Step 1: Add failing registered-agent recovery tests**

Add these methods to `TestRegisteredAgentLifecycle`:

```python
def test_recover_from_error_returns_to_idle_and_preserves_error_count(self):
    agent = self._make_agent()
    agent.assign(AgentTask(agent_name="test_agent", prompt="p"))
    agent.fail()

    recovered = agent.recover_from_error()

    self.assertTrue(recovered)
    self.assertEqual(agent.status, AgentStatus.IDLE)
    self.assertEqual(agent.errors_count, 1)
    self.assertIsNone(agent.current_task)

def test_recover_from_error_refuses_non_error_states(self):
    for status in (AgentStatus.IDLE, AgentStatus.BUSY, AgentStatus.SHUTDOWN):
        with self.subTest(status=status):
            agent = self._make_agent()
            agent.status = status
            self.assertFalse(agent.recover_from_error())
            self.assertEqual(agent.status, status)

def test_recover_from_error_refuses_nonrecoverable_error(self):
    agent = self._make_agent()
    agent.assign(AgentTask(agent_name="test_agent", prompt="p"))
    agent.fail(recoverable=False)

    self.assertFalse(agent.recover_from_error())
    self.assertEqual(agent.status, AgentStatus.ERROR)
    self.assertEqual(agent.errors_count, 1)
```

- [ ] **Step 2: Add failing orchestrator boundary tests**

Add a `TestOrchestratorRecovery` class:

```python
class TestOrchestratorRecovery(unittest.TestCase):
    def test_recover_agent_preserves_failed_result_history_and_stats(self):
        orchestrator = Orchestrator()

        def fail(_task):
            raise RuntimeError("failed")

        orchestrator.register("worker", fail)
        result = orchestrator.dispatch(
            AgentTask(task_id="failed-task", agent_name="worker", prompt="task")
        )

        self.assertEqual(result.status, "error")
        self.assertTrue(orchestrator.recover_agent("worker"))
        self.assertEqual(orchestrator.list_agents()[0].status, "idle")
        self.assertEqual(orchestrator.list_agents()[0].errors_count, 1)
        self.assertEqual(orchestrator.collect(task_id="failed-task")[0].status, "error")
        self.assertEqual(orchestrator.get_stats()["total_errors"], 1)

    def test_recover_agent_refuses_missing_and_non_error_agents(self):
        orchestrator = Orchestrator()
        orchestrator.register("worker", lambda _task: "ok")

        self.assertFalse(orchestrator.recover_agent("missing"))
        self.assertFalse(orchestrator.recover_agent("worker"))
        orchestrator._agents["worker"].assign(
            AgentTask(agent_name="worker", prompt="busy")
        )
        self.assertFalse(orchestrator.recover_agent("worker"))
        self.assertEqual(orchestrator.list_agents()[0].status, "busy")

    def test_recover_agent_does_not_recover_timeout(self):
        orchestrator = Orchestrator()

        def slow(_task):
            time.sleep(0.1)
            return "late"

        orchestrator.register("worker", slow)
        result = orchestrator.dispatch(
            AgentTask(agent_name="worker", prompt="task", timeout=0.01)
        )

        self.assertEqual(result.status, "timeout")
        self.assertFalse(orchestrator.recover_agent("worker"))
        self.assertEqual(orchestrator.list_agents()[0].status, "error")
```

Add `TestOrchestratorRecovery` to the file's explicit `run_all_tests()` class list.

- [ ] **Step 3: Run the new tests and confirm red**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended.TestRegisteredAgentLifecycle tests.test_orchestrator_extended.TestOrchestratorRecovery -v
```

Expected: `AttributeError` for both missing recovery methods.

- [ ] **Step 4: Implement the atomic state transition**

Initialize `self._error_recoverable = False`. Update state transitions so
`assign()`, `complete()`, and `reset()` clear the marker. Change `fail()` and add
the recovery method:

```python
def fail(self, *, recoverable: bool = True) -> None:
    with self._lock:
        self.errors_count += 1
        self.status = AgentStatus.ERROR
        self.current_task = None
        self._error_recoverable = recoverable

def recover_from_error(self) -> bool:
    """Return a completed error state to IDLE without changing counters."""
    with self._lock:
        if self.status != AgentStatus.ERROR or not self._error_recoverable:
            return False
        self.status = AgentStatus.IDLE
        self.current_task = None
        self._error_recoverable = False
        return True
```

In the timeout branch of `Orchestrator.dispatch()`, call:

```python
agent.fail(recoverable=False)
```

The ordinary exception branch keeps `agent.fail()` and is recoverable.

Add to `Orchestrator` near registration and lifecycle methods:

```python
def recover_agent(self, name: str) -> bool:
    """Recover a registered agent only when its current state is ERROR."""
    agent = self._agents.get(name)
    if agent is None:
        return False
    return agent.recover_from_error()
```

- [ ] **Step 5: Run focused orchestrator suites**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v
```

Expected: all orchestrator tests pass, including timeout non-recovery.

- [ ] **Step 6: Commit the recovery boundary**

```powershell
git add -- src/core/brain/orchestrator.py tests/test_orchestrator_extended.py
git diff --cached --check
git commit -m "feat: add explicit agent error recovery"
```

### Task 2: Recover Role For The Next Request

**Files:**
- Modify: `tests/test_agent_factory.py`
- Modify: `src/core/brain/agent_factory.py`

**Interfaces:**
- Consumes: `Orchestrator.recover_agent(name: str) -> bool` from Task 1.
- Produces: sequential role dispatch statuses `[error, success]` for manager responses `[error, success]`.

- [ ] **Step 1: Add the failing cross-request regression**

Add to `TestOllamaRoleExecution`:

```python
def test_role_recovers_for_next_request_after_execution_error(self):
    manager = Mock()
    manager.chat.side_effect = [
        {"error": "offline"},
        self._response("recovered"),
    ]
    factory = AgentFactory(ollama_manager=manager)

    first = factory.dispatch_by_role("engineer", "first task")
    second = factory.dispatch_by_role("engineer", "second task")

    self.assertEqual(first.status, "error")
    self.assertEqual(first.message, "Ollama role execution failed")
    self.assertEqual(second.status, "success")
    self.assertEqual(second.message, "recovered")
    self.assertEqual(manager.chat.call_count, 2)
    info = factory.orchestrator.list_agents()[0]
    self.assertEqual(info.status, "idle")
    self.assertEqual(info.errors_count, 1)
    self.assertEqual(info.tasks_completed, 1)
```

- [ ] **Step 2: Run the regression and confirm red**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory.TestOllamaRoleExecution.test_role_recovers_for_next_request_after_execution_error -v
```

Expected: second result is `busy`, message says the agent is busy, and manager call count is 1.

- [ ] **Step 3: Recover only after an ordinary error result**

Immediately after `result = self.orchestrator.dispatch(task)` in
`dispatch_by_role()` add:

```python
if result.status == "error":
    self.orchestrator.recover_agent(profile.name)
```

Do not call recovery for `timeout`, `busy`, `failed`, or successful results.

- [ ] **Step 4: Run factory and orchestrator regressions**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory tests.test_agent_factory_extended tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v
```

Expected: all tests pass; the failed result remains recorded as `error` and the second request succeeds.

- [ ] **Step 5: Commit the factory integration**

```powershell
git add -- src/core/brain/agent_factory.py tests/test_agent_factory.py
git diff --cached --check
git commit -m "fix: recover role after completed execution error"
```

### Task 3: Iteration 127 Evidence And Full Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/GITHUB_LEARNING_REPORT.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_127.md`
- Delete: `docs/reports/AUDIT_REPORT_117.md`

**Interfaces:**
- Consumes: measured test results from Tasks 1 and 2.
- Produces: current Iteration 127 evidence with reports 118-127.

- [ ] **Step 1: Record Phase 3 and state semantics**

Record the three focused search queries, their lack of eligible direct matches,
and the reference metadata for Microsoft AutoGen (59,730 Stars, CC-BY-4.0),
Pydantic AI (18,521 Stars, MIT), and LangGraph (37,295 Stars, MIT), all active on
2026-07-14. State that no dependency was adopted because the fix is an internal
state transition and timeout safety differs from completed handler errors.

- [ ] **Step 2: Advance the project ledger**

Add Iteration 127 to `CHANGELOG.md` and `PROJECT_ANALYSIS.md`; set `AGENTS.md` to
Iteration 127 and the measured discovery count; add `AUDIT_REPORT_127.md`; update
the report index and remove `AUDIT_REPORT_117.md` so exactly 118-127 remain.
Document timeout cancellation/process isolation and controlled role tools as the
remaining Phase 11 work.

- [ ] **Step 3: Run focused and documentation tests**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_agent_factory tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry -v
.\venv\Scripts\python.exe -m unittest tests.test_readme tests.test_docs_setup tests.test_iteration_ledger -v
```

Expected: both commands exit 0.

- [ ] **Step 4: Run full Python gates**

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
```

Expected: aggregate remains 208 and complete discovery includes five new tests.

- [ ] **Step 5: Run frontend gates**

```powershell
Set-Location frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
```

Expected: Vitest, Playwright, typecheck, and build exit 0; the desktop-only mobile-navigation test may remain skipped by its project condition.

- [ ] **Step 6: Run final integrity checks**

```powershell
git diff --check
git status --short
Get-ChildItem docs/reports/AUDIT_REPORT_*.md
```

Expected: no whitespace errors, exactly ten reports 118-127, and only intended Iteration 127 changes plus preserved pre-existing worktree changes.
