# Role Worker Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a process-owned asynchronous role-task channel with confirmed timeout/cancellation terminal states and OpenAPI 1.12 lifecycle endpoints.

**Architecture:** Immutable protocol contracts live in `core/contracts`; the parent-authoritative process supervisor lives in `core/brain`; a fixed production runner constructs child-local Ollama dependencies; FastAPI composes the service and exposes task lifecycle routes. Existing synchronous role dispatch remains unchanged.

**Tech Stack:** Python 3.10+ standard library multiprocessing/threading/dataclasses, existing FastAPI and Ollama manager, OpenAPI 3.1 JSON, unittest.

## Global Constraints

- Worker protocol version is exactly `1`.
- Task timeout is an integer from `1` through `300` seconds.
- Parent process state is authoritative; child messages never mutate records directly.
- `timeout` and `cancelled` require confirmed process termination.
- Result/error payload retention is at most `1_048_576` UTF-8 bytes.
- Task history is bounded and defaults to `100` records.
- HTTP input cannot choose a runner, command, environment, working directory, or capability token.
- New behavior follows red-green-refactor and each task ends with a focused commit.

---

### Task 1: Versioned Worker Protocol Contracts

**Files:**
- Create: `src/core/contracts/worker_protocol.py`
- Modify: `src/core/contracts/__init__.py`
- Create: `tests/test_worker_protocol.py`

**Interfaces:**
- Produces: `WorkerTaskStatus`, `WorkerTaskRequest`, `WorkerEvent`, and `WorkerTaskRecord`.
- Produces: strict `to_dict()` methods and validated constructors.

- [ ] Write tests proving timeout bounds, terminal status membership, timestamp/ID validation, enum serialization, and rejection of unknown serialized fields.
- [ ] Run `\.\venv\Scripts\python.exe -m unittest tests.test_worker_protocol -v` and confirm the import fails.
- [ ] Implement frozen slot dataclasses, exact schema version validation, timezone-aware timestamps, and explicit serialization.
- [ ] Re-run the focused test and `compileall` for the new contract.
- [ ] Commit with exact paths using `feat: define role worker protocol`.

### Task 2: Parent-Authoritative Process Supervisor

**Files:**
- Create: `src/core/brain/role_worker.py`
- Create: `tests/worker_fixtures.py`
- Create: `tests/test_role_worker.py`

**Interfaces:**
- Produces: `RoleWorkerSupervisor.submit(request)`, `get(task_id)`, `list(limit)`, `cancel(task_id)`, and `shutdown()`.
- Consumes: a fixed constructor-injected top-level runner and trusted configuration; neither is accepted from task input.

- [ ] Write spawn-safe fixture runners for success, exception, sleep, abrupt exit, oversized output, and late-message cases.
- [ ] Write failing tests for success, `failed`, `crashed`, confirmed `timeout`, confirmed `cancelled`, bounded history, duplicate cancellation, stale event rejection, and shutdown cleanup.
- [ ] Run `\.\venv\Scripts\python.exe -m unittest tests.test_role_worker -v` and confirm the supervisor import fails.
- [ ] Implement one process per task, a one-way pipe, child heartbeat thread, parent monitor thread, monotonic event filtering, terminal-state guards, and bounded termination.
- [ ] Re-run the focused tests and assert every test-owned process is dead during teardown.
- [ ] Commit with exact paths using `feat: supervise terminable role workers`.

### Task 3: Fixed Role Runner and Service Telemetry

**Files:**
- Modify: `src/core/brain/role_worker.py`
- Modify: `tests/test_role_worker.py`

**Interfaces:**
- Produces: `execute_role_task(request_dict, trusted_config)` as the only production runner.
- Returns: `{"dispatch": DispatchResult.to_dict(), "usage": {"prompt_tokens": int, "completion_tokens": int}}`.

- [ ] Add a local Ollama HTTP fixture test that proves the child executes a built-in role and returns deterministic content and token counts.
- [ ] Confirm the test fails while only generic fixture runners exist.
- [ ] Implement child-local `OllamaManager`/`AgentFactory` composition and normalize all upstream exceptions to the existing safe role error.
- [ ] Add a parent terminal callback that records returned prompt/completion counts in the service manager.
- [ ] Re-run worker, agent factory, and Ollama manager tests.
- [ ] Commit with exact paths using `feat: execute role tasks in worker processes`.

### Task 4: FastAPI Role Task Lifecycle

**Files:**
- Modify: `src/main_fastapi.py`
- Modify: `tests/test_main_fastapi.py`

**Interfaces:**
- Adds: `AppState.role_tasks` injection and default supervisor composition.
- Adds: create/list/get/cancel routes under `/api/roles/tasks`.

- [ ] Add failing TestClient cases for `202` creation, list/get, confirmed cancellation, invalid input, unknown task, terminal conflict, and lifespan shutdown.
- [ ] Run only the new test class and confirm routes or `AppState.role_tasks` are missing.
- [ ] Compose the fixed supervisor from trusted Ollama base URL/model values, define Pydantic request validation, and add static routes before `/api/roles/{role_name}`.
- [ ] Shut down the supervisor first in lifespan cleanup.
- [ ] Re-run the new class and the complete `tests.test_main_fastapi` module.
- [ ] Commit with exact paths using `feat: expose role task lifecycle`.

### Task 5: OpenAPI 1.12 Contract

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Declares: Worker task request/record/list schemas and lifecycle paths.
- Extends: `AgentResult.status.enum` with existing outcomes plus `cancelled`, `crashed`, and `failed`.

- [ ] Keep the existing failing 1.12 tests and add schema/response validation for all new success and error bodies.
- [ ] Add the three path objects, stable error envelopes, `202` creation response, and the bounded list query.
- [ ] Run `\.\venv\Scripts\python.exe -m unittest tests.test_api_contract -v` until every contract and route-coverage test passes.
- [ ] Commit the contract and its tests together using `feat: declare role worker lifecycle api`.

### Task 6: Gates and Iteration Evidence

**Files:**
- Modify: `tests/run_all.py`
- Modify: `tests/test_run_all_coverage.py`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Modify: `CHANGELOG.md`
- Create: `docs/reports/AUDIT_REPORT_130.md`

- [ ] Register worker protocol/supervisor/API tests in the aggregate suite and make the coverage guard fail first.
- [ ] Run focused Worker tests, aggregate tests, full discovery, compileall, frontend Vitest/typecheck/build/Playwright, and required-services local integration.
- [ ] Record literal current counts and outcomes; do not copy Iteration 129 estimates.
- [ ] Mark only this Phase B slice complete. Keep legacy synchronous route migration and persistent task recovery explicit as the next work.
- [ ] Review changed files for placeholders, absolute paths, secret values, arbitrary runner exposure, and unconfirmed terminal transitions.
- [ ] Create the exact-path Iteration 130 checkpoint using `feat: add terminable role task lifecycle`.
