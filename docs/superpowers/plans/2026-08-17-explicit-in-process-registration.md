# Explicit In-Process Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give process-local Orchestrator handlers an explicit registration API while preserving `register()` as a source-compatible, warning-emitting migration wrapper.

**Architecture:** Move the existing thread-backed registration body into `register_in_process()` and make `register()` delegate to it after emitting a `DeprecationWarning`. Production and test call sites that intentionally require closures or other process-local callables will name that execution mode directly; stable module-level functions can continue opting into the existing `register_worker()` child-process path.

**Tech Stack:** Python 3.10+, standard-library `warnings`, existing thread-backed `Orchestrator`, `unittest`.

## Global Constraints

- Preserve the exact `register(name, handler, capabilities=None) -> Orchestrator` signature and chaining behavior.
- Never inspect a callable to auto-select, promote, demote, or fall back between Worker and in-process execution.
- Direct callers of `register_in_process()` must not receive a deprecation warning.
- Keep `register_declared()`, `register_worker()`, cancellation, result/history/statistics behavior, HTTP routes, and OpenAPI schemas unchanged.
- Preserve all unrelated staged and unstaged work; do not commit, stage, reset, or clean the dirty `main` worktree.
- Keep full Ruff cleanup outside this iteration; compare the result with the known 152-finding baseline.

---

### Task 1: Add the executable migration contract

**Files:**
- Modify: `tests/test_orchestrator_extended_v2.py`

**Interfaces:**
- Consumes: planned `Orchestrator.register_in_process(name, handler, capabilities=None) -> Orchestrator` and compatibility `register()`.
- Produces: one regression for explicit closure execution without warnings and one regression for the deprecated wrapper's unchanged parent-process execution.

- [ ] **Step 1: Add a failing test for explicit in-process registration**

Add this test to `TestOrchestratorImportableWorker` before its Worker-specific tests:

```python
def test_explicit_in_process_closure_returns_self_without_warning(self):
    orch = Orchestrator()

    def local_handler(task):
        return {"pid": os.getpid(), "task_id": task.task_id}

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        registered = orch.register_in_process("local", local_handler)

    try:
        result = orch.dispatch(
            AgentTask(
                task_id="local-task",
                agent_name="local",
                prompt="inspect",
                timeout=1,
            )
        )
    finally:
        orch.shutdown()

    self.assertIs(registered, orch)
    self.assertFalse(
        any(item.category is DeprecationWarning for item in caught)
    )
    self.assertEqual(result.status, "success")
    self.assertEqual(result.result["pid"], os.getpid())
    self.assertEqual(result.result["task_id"], "local-task")
```

Also add `import warnings` beside the standard-library imports.

- [ ] **Step 2: Tighten the legacy compatibility test around the warning contract**

Replace `test_legacy_callable_registration_stays_in_parent_process` with:

```python
def test_register_warns_and_keeps_importable_callable_in_parent_process(self):
    orch = Orchestrator()
    with self.assertWarnsRegex(
        DeprecationWarning,
        r"register_worker\(\).*register_in_process\(\)",
    ):
        registered = orch.register(
            "legacy",
            orchestrator_worker_fixtures.project_task,
        )
    try:
        result = orch.dispatch(
            AgentTask(
                task_id="legacy-task",
                agent_name="legacy",
                prompt="inspect",
                timeout=1,
            )
        )
    finally:
        orch.shutdown()

    self.assertIs(registered, orch)
    self.assertEqual(result.status, "success")
    self.assertEqual(result.result["pid"], os.getpid())
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended_v2.TestOrchestratorImportableWorker -v`

Expected: the explicit test errors with `AttributeError: 'Orchestrator' object has no attribute 'register_in_process'`, and the compatibility test fails because `register()` emits no `DeprecationWarning`.

### Task 2: Implement the explicit API and migrate production

**Files:**
- Modify: `src/core/brain/orchestrator.py`
- Modify: `src/core/brain/agent_factory.py`
- Test: `tests/test_orchestrator_extended_v2.py`
- Test: `tests/test_agent_factory.py`
- Test: `tests/test_agent_factory_extended.py`

**Interfaces:**
- Consumes: the existing `_RegisteredAgent` thread-backed registration body.
- Produces: `register_in_process(name, handler, capabilities=None) -> Orchestrator`; `register()` remains compatible and emits the exact migration warning.

- [ ] **Step 1: Move the current registration body behind the explicit method**

Add `import warnings`, retain the existing method signature, and implement the two methods as follows:

```python
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
    logger.info(
        "In-process agent registered: '%s' capabilities=%s",
        name,
        capabilities,
    )
    return self
```

Update the Orchestrator usage example to call `register_in_process()` directly so maintained documentation does not advertise the deprecated API.

- [ ] **Step 2: Make AgentFactory's closure registration explicit**

In `AgentFactory.dispatch_by_role()`, change only the method name:

```python
self.orchestrator.register_in_process(
    profile.name,
    handler=self._default_handler(profile),
    capabilities=profile.capabilities,
)
```

- [ ] **Step 3: Run the focused contract and production consumer tests**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_orchestrator_extended_v2.TestOrchestratorImportableWorker tests.test_agent_factory tests.test_agent_factory_extended -v`

Expected: all selected tests pass; direct `register_in_process()` calls produce no deprecation warning and `AgentFactory` behavior is unchanged.

### Task 3: Migrate intentional in-process fixtures

**Files:**
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_orchestrator_extended.py`
- Modify: `tests/test_orchestrator_extended_v2.py`
- Modify: `tests/test_orchestrator_retry.py`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Consumes: `register_in_process()` from Task 2.
- Produces: warning-free maintained tests in which every thread-path registration is explicit, while the single compatibility regression continues to call `register()`.

- [ ] **Step 1: Replace intentional thread-path registrations**

Mechanically change `.register(` to `.register_in_process(` in the five listed test files. Restore only `test_register_warns_and_keeps_importable_callable_in_parent_process` to `.register(`. Preserve test names, inputs, assertions, formatting, and every `register_declared()`/`register_worker()` call.

- [ ] **Step 2: Verify the compatibility surface is isolated**

Run: `rg -n "\.register\(" src/core/brain tests -g "*.py"`

Expected: the only Orchestrator hits are the wrapper's maintained usage text or definition and the focused compatibility test; unrelated registries and `atexit.register()` are outside the searched paths or clearly distinct.

- [ ] **Step 3: Run all Orchestrator and API contract tests**

Run: `.\venv\Scripts\python.exe -m unittest tests.test_orchestrator tests.test_orchestrator_extended tests.test_orchestrator_extended_v2 tests.test_orchestrator_retry tests.test_api_contract -v`

Expected: all selected tests pass without unexpected deprecation warnings; parent-process timeout quarantine, Worker cancellation, HTTP behavior, and public response shapes remain unchanged.

### Task 4: Self-review, full verification, and Iteration 147 evidence

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_147.md`
- Delete: `docs/reports/AUDIT_REPORT_137.md`

**Interfaces:**
- Consumes: fresh verification outputs and the rolling ten-report policy.
- Produces: accurate Iteration 147 project state, test counts, migration guidance, remaining boundaries, and reproducible evidence.

- [ ] **Step 1: Review implementation boundaries and diff**

Confirm that `register()` only warns and delegates, `register_in_process()` owns the unchanged thread registration logic, no callable classification or fallback exists, `AgentFactory` explicitly selects the closure path, the one compatibility test alone uses the deprecated method, and no HTTP/OpenAPI/result/history contract changed.

- [ ] **Step 2: Run Python verification and record exact totals**

Run:

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
.\venv\Scripts\python.exe -m ruff check src tests scripts
```

Expected: aggregate and discovery suites pass except the two established skips; compileall exits 0; Ruff is compared with the existing 152 workspace findings rather than treated as a new clean baseline.

- [ ] **Step 3: Run frontend and integration gates**

Run:

```powershell
Set-Location frontend
npm test -- --run
npm run test:e2e
npm run typecheck
npm run build
Set-Location ..
.\venv\Scripts\python.exe scripts\ci_local_integration.py --require-services
git diff --check
```

Expected: Vitest, Playwright subject to its documented conditional skip, typecheck, build, local integration, and whitespace validation pass.

- [ ] **Step 4: Update the rolling project evidence using only fresh results**

Create `AUDIT_REPORT_147.md`, remove only the verified oldest report `AUDIT_REPORT_137.md`, and update the six maintained navigation/status documents with actual test totals. Document the three explicit modes: static built-in runner via `register_declared()`, stable top-level callable via `register_worker()`, and intentional process-local callable via `register_in_process()`; identify `register()` as deprecated compatibility. Keep OS-level isolation and generic task persistence listed as remaining work.

- [ ] **Step 5: Perform final self-review and evidence checks**

Run:

```powershell
rg -n "TB[D]|TO[D]O|Current verified test baseline for Iteration 14[6]|Iteration 13[7]-14[6]|62[5] total \(623 passed|156[8] total \(1566 passed" docs/superpowers/plans/2026-08-17-explicit-in-process-registration.md README.md AGENTS.md docs/DEVELOPMENT_GUIDE.md docs/reports/PROJECT_ANALYSIS.md docs/reports/README.md docs/reports/AUDIT_REPORT_147.md
git diff --check
git status --short
```

Expected: no plan placeholders or stale current baseline/window text remain (historical Iteration 146 references may remain in chronology), whitespace validation passes, and status shows only the preserved prior work plus the scoped Iteration 147 changes.
