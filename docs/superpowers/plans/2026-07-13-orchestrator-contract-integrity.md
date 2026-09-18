# Orchestrator Contract Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore evidence-backed parity for the shared orchestrator API contract across Python HTTPServer, FastAPI, and Express.

**Architecture:** Keep `contracts/core-api.openapi.json` as the single wire contract. Make each adapter normalize the same history and dispatch boundaries while leaving core orchestration behavior unchanged. Use deterministic local handlers and loopback fixtures for cross-adapter verification.

**Tech Stack:** Python stdlib `HTTPServer`, FastAPI/Pydantic, Node.js Express, JSON OpenAPI 3.1, unittest, Vitest.

## Global Constraints

- Shared history limits are inclusive `1..100`; default is `10`.
- Shared dispatch defaults are `timeout=300` and `priority=1`; priority is inclusive `0..3`.
- Shared dispatch timeout is inclusive `1..300`; agent and prompt text must contain a non-whitespace Unicode scalar value.
- JSON errors use the existing nested `{ "error": { "code": "...", "message": "..." } }` envelope.
- Do not add runtime dependencies.
- Do not modify `/api/roles*`, terminal policy, frontend role UI, or core Orchestrator internals.
- Preserve unrelated user changes in the dirty worktree.
- Production code changes follow TDD: each behavior change starts with a failing regression.

---

### Task 1: FastAPI orchestrator bounds

**Files:**
- Modify: `src/main_fastapi.py:733-764`
- Test: `tests/test_main_fastapi.py:240-258`

**Interfaces:**
- Consumes: `state.orchestrator.collect(limit=...)` and `AgentTask`.
- Produces: FastAPI history requests clamped to `1..100`, and dispatch requests with explicit `timeout`/`priority` validation matching OpenAPI.

- [ ] **Step 1: Write the failing tests**

Add tests that request `/api/orchestrator/history?limit=101` and assert the
orchestrator receives `100`, and that a dispatch request containing
`{"agent_name":"analyzer","prompt":"ping","timeout":45,"priority":3}`
passes those values into the created task.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main_fastapi.TestMainFastapiIntegration
```

Expected: the new bound/forwarding assertions fail against the current
implementation.

- [ ] **Step 3: Implement the minimal FastAPI change**

Use a typed query bound or explicit normalization so `limit` is always within
`1..100`. Keep the existing response envelope. In dispatch, preserve the
existing request parsing but validate integer bounds before creating
`AgentTask`, with defaults `timeout=300` and `priority=1`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same unittest command and require all tests to pass.

- [ ] **Step 5: Commit only Task 1 files**

```powershell
git add src/main_fastapi.py tests/test_main_fastapi.py
git commit -m "fix: align fastapi orchestrator bounds"
```

---

### Task 2: Python HTTPServer dispatch parity

**Files:**
- Modify: `src/main.py:653-673`
- Test: `tests/test_main.py:621-641`

**Interfaces:**
- Consumes: `JARVISHandler.handle_orchestrator_dispatch` and `AgentTask`.
- Produces: HTTPServer dispatch with the same defaults and priority forwarding as FastAPI.

- [ ] **Step 1: Write the failing test**

Add a handler-level test with JSON body
`{"agent_name":"analyzer","prompt":"ping","timeout":45,"priority":3}`.
Patch `state.orchestrator.dispatch`, capture its `AgentTask`, and assert
`timeout == 45` and `priority == 3`.

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_main.TestJARVISHandlerHandleMethods
```

Expected: the priority assertion fails because the current handler ignores
`priority` and defaults `timeout` to `30`.

- [ ] **Step 3: Implement the minimal HTTPServer change**

Read `timeout` with default `300`, read `priority` with default `1`, validate
both as integers in the documented ranges, and pass both to `AgentTask`.
Return the existing nested error envelope for invalid values.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same unittest command and require all tests to pass.

- [ ] **Step 5: Commit only Task 2 files**

```powershell
git add src/main.py tests/test_main.py
git commit -m "fix: align httpserver orchestrator dispatch"
```

---

### Task 3: Express fixture contract completeness

**Files:**
- Modify: `frontend/server.test.js:171-181`
- Test: `frontend/server.test.js:446-466`

**Interfaces:**
- Consumes: the existing Core API fixture and Express proxy test.
- Produces: a deterministic dispatch fixture matching `AgentResult` exactly enough for contract validation.

- [ ] **Step 1: Write the failing assertion**

Extend the existing dispatch proxy assertion to require `error` and
`duration_ms` fields in the returned JSON, in addition to the existing task,
agent, result, and status fields.

- [ ] **Step 2: Run the focused Vitest and verify RED**

```powershell
cd frontend
npm test -- --run server.test.js -t "shared orchestrator"
```

Expected: the assertion fails because the fixture omits `error` and
`duration_ms`.

- [ ] **Step 3: Implement the minimal fixture change**

Return `error: null` and `duration_ms: 0` from the fixture. Preserve the
request-body parsing and proxy behavior.

- [ ] **Step 4: Run the focused Vitest and verify GREEN**

Run the same command and require it to pass.

- [ ] **Step 5: Commit only Task 3 files**

```powershell
git add frontend/server.test.js
git commit -m "test: complete orchestrator proxy fixture"
```

---

### Task 4: Shared OpenAPI and schema validator

**Files:**
- Modify: `contracts/core-api.openapi.json:425-434`
- Test: `tests/test_api_contract.py:411-435`

**Interfaces:**
- Consumes: the existing schema assertion helper.
- Produces: `maximum: 100` for history `limit`, and validator support for numeric maximum constraints.

- [ ] **Step 1: Write the failing validator test**

Add a schema assertion showing `{ "priority": 4 }` fails against an integer
schema with `maximum: 3`, while `3` passes.

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_schema_validation_enforces_const_minimum_and_strict_integer
```

Expected: the over-maximum value is incorrectly accepted.

- [ ] **Step 3: Implement the minimal contract and validator change**

Add `maximum: 100` beside the existing history `minimum: 1`. Extend only the
numeric schema branch in `_assert_json_shape` to reject values above
`schema["maximum"]`; retain strict integer, minimum, const, and minLength
behavior.

- [ ] **Step 4: Run contract tests and verify GREEN**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_api_contract
```

- [ ] **Step 5: Commit only Task 4 files**

```powershell
git add contracts/core-api.openapi.json tests/test_api_contract.py
git commit -m "test: enforce orchestrator contract maximums"
```

---

### Task 5: Real three-adapter dispatch harness

**Files:**
- Modify: `tests/test_api_contract.py:724-835`
- Modify: `frontend/server.test.js:171-181`

**Interfaces:**
- Consumes: Task 1-4 adapter behavior and `AgentResult` OpenAPI schema.
- Produces: loopback evidence that Python HTTPServer, FastAPI, and Express all return schema-valid dispatch results.

- [ ] **Step 1: Add failing live harness assertions**

Send the same JSON dispatch payload to all three adapters. Require HTTP `200`,
validate the `AgentResult` schema, and assert `task_id`, `agent_name`,
`duration_ms`, `status`, `result`, and `error` are present. Add one negative
request missing `prompt` and assert the adapter's declared error response.

- [ ] **Step 2: Run the live contract test and verify RED**

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas
```

Expected: the new dispatch check fails before all adapter fixes are present.

- [ ] **Step 3: Implement only harness/fixture corrections**

Use existing dynamic ports, fixture lifecycle, and `_post_json` helpers. Do
not loosen the schema or accept partial responses.

- [ ] **Step 4: Run the live contract test and verify GREEN**

Run the same command and require all three adapters to pass.

- [ ] **Step 5: Commit only Task 5 files**

```powershell
git add tests/test_api_contract.py frontend/server.test.js
git commit -m "test: verify orchestrator dispatch across adapters"
```

---

### Task 6: Iteration evidence and full verification

**Files:**
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/GITHUB_LEARNING_REPORT.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_124.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: completed code and test outputs from Tasks 1-5.
- Produces: current iteration evidence with no stale claims about orchestrator parity.

- [ ] **Step 1: Run the verification matrix**

```powershell
.\venv\Scripts\python.exe tests/run_all.py
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\venv\Scripts\python.exe -m compileall -q src tests scripts
cd frontend; npm test -- --run
cd frontend; npm run test:e2e
cd frontend; npm run typecheck
cd frontend; npm run build
git diff --check
```

- [ ] **Step 2: Record exact counts and residual risks**

Update only claims supported by the current commands. Keep role-specific
routes explicitly out of the shared contract and record any remaining test
environment skips.

- [ ] **Step 3: Commit evidence files**

```powershell
git add AGENTS.md CHANGELOG.md docs/reports/PROJECT_ANALYSIS.md docs/reports/GITHUB_LEARNING_REPORT.md docs/reports/README.md docs/reports/AUDIT_REPORT_124.md
git commit -m "docs: record orchestrator contract integrity iteration"
```
