# Memory Endpoint Test State Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent all known memory endpoint tests from writing fixture records into the repository's real `.auto-memory` directory.

**Architecture:** Keep production behavior unchanged and use the dependency-injection seams already present in each service adapter. A discovery-only behavioral guard patches the process-global stores to fail, then runs the six writer tests to prove they own isolated temporary stores.

**Tech Stack:** Python 3.10+, stdlib `unittest`/`tempfile`, FastAPI `TestClient`.

## Global Constraints

- Do not read, delete, rewrite, or repair existing `.auto-memory` entries.
- Do not change public HTTP/FastAPI memory contracts.
- Every temporary FastAPI state must shut down before its directory is removed.
- Preserve unrelated Iteration 225-237 working-tree changes.

---

### Task 1: Add the failing default-store isolation guard

**Files:**
- Modify: `tests/test_run_all_coverage.py`

**Interfaces:**
- Consumes: the default stores exposed by `test_main._main.state`, `test_main_extended.state`, and `main_fastapi._default_state`.
- Produces: `TestMemoryEndpointTestIsolation.test_memory_writer_tests_never_use_default_stores`.

- [ ] **Step 1: Write the failing test**

Add a test class that loads the six exact writer test IDs, patches each unique
default store instance's `store()` to raise `AssertionError`, runs the nested suite,
and reports nested errors/failures through `self.assertTrue(result.wasSuccessful())`.

- [ ] **Step 2: Run the guard and verify RED**

Run: `python -m unittest tests.test_run_all_coverage.TestMemoryEndpointTestIsolation -v`

Expected: FAIL because the current writer tests call at least one patched global
store.

### Task 2: Give every writer test explicit temporary storage

**Files:**
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_extended.py`
- Modify: `tests/test_main_fastapi.py`
- Modify: `tests/test_main_fastapi_extended.py`

**Interfaces:**
- Consumes: `MemoryStore(memory_dir=...)`, handler `app_state`,
  `AppState(memory_dir=...)`, and `create_app(state)`.
- Produces: the same endpoint assertions without process-global memory writes.

- [ ] **Step 1: Isolate stdlib handler writes**

Wrap each writer in `TemporaryDirectory()`, create a temporary `MemoryStore`, and
pass `SimpleNamespace(memory_store=memory_store)` through `_make_handler(...,
app_state=...)`.

- [ ] **Step 2: Isolate FastAPI writes**

For each writer, create `AppState(memory_dir=temporary)`, call `create_app(state)`,
and issue the request inside `with TestClient(isolated_app, ...) as client:`.

- [ ] **Step 3: Run the guard and verify GREEN**

Run: `python -m unittest tests.test_run_all_coverage.TestMemoryEndpointTestIsolation -v`

Expected: one test passes and every nested writer retains its original assertions.

- [ ] **Step 4: Run affected modules**

Run: `python -m unittest tests.test_main tests.test_main_extended tests.test_main_fastapi tests.test_main_fastapi_extended tests.test_run_all_coverage`

Expected: all tests pass with the project's existing conditional skips only.

### Task 3: Synchronize evidence and validate the iteration

**Files:**
- Modify: `tests/run_all.py` only if the new guard changes canonical registration.
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_238.md`
- Remove from rolling report window: `docs/reports/AUDIT_REPORT_228.md`

**Interfaces:**
- Consumes: fresh verification totals from the current worktree.
- Produces: Iteration 238 evidence without changing historical Iteration 237 counts.

- [ ] **Step 1: Review the focused diff**

Confirm only isolated state ownership, the behavioral guard, and synchronized
iteration evidence are added. Confirm `.auto-memory` is not part of the diff.

- [ ] **Step 2: Run backend gates**

Run the focused modules, `python tests/run_all.py`,
`python scripts/discover_tests.py --timeout 1800`,
`python -m ruff check src tests scripts`, and
`python -m compileall -q src tests scripts`.

- [ ] **Step 3: Run frontend gates**

From `frontend`, run `npm test -- --run`, `npm run typecheck`, `npm run build`, and
`npm run test:e2e`.

- [ ] **Step 4: Run final integrity checks**

Run `git diff --check`, compare a pre/post fingerprint of `.auto-memory`, and inspect
the exact task diff before updating the Goal.

