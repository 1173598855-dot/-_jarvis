# Bounded API Query Inputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce one stable 32 KiB raw query budget at the Python HTTP, FastAPI, and Express API boundaries.

**Architecture:** Add a pre-routing check to the standard-library server, an ASGI middleware to FastAPI, and an Express middleware before API handlers. Preserve route-specific validation and stream checks, then document the shared 413 response in OpenAPI and the iteration ledger.

**Tech Stack:** Python `http.server`, FastAPI/ASGI, Node.js/Express, OpenAPI JSON, `unittest`, Vitest.

## Global Constraints

- Count only raw UTF-8 query bytes after `?`; reject values strictly greater than `32 * 1024`.
- Apply the new ingress check only to `/api/` requests.
- Return `REQUEST_QUERY_TOO_LARGE` and `Request query exceeds the 32 KiB limit` with HTTP 413.
- Preserve all unrelated user changes and existing route-specific validation.

---

### Task 1: Add failing adapter regressions

**Files:**
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi_extended.py`
- Modify: `frontend/server.test.js`
- Modify: `tests/test_api_contract.py`

**Interfaces:** Tests assert the existing error envelope and the shared `MAX_REQUEST_QUERY_BYTES` budget; no production interface changes are assumed.

- [x] **Step 1: Write the failing tests**

  Add one-byte-over-budget API requests for the Python route dispatcher, the
  FastAPI health route, and the Express health route. Add exact-budget requests
  that remain successful. Assert that the Python route handler and FastAPI
  downstream state are not invoked, and that Express returns the same JSON
  error. Extend the contract test to require the 413 response on every
  documented query-bearing operation.

- [x] **Step 2: Run the focused tests and verify RED**

  Run `.\venv\Scripts\python.exe -m unittest tests.test_main tests.test_main_fastapi_extended tests.test_api_contract` and `cd frontend; npm test -- --run server.test.js`.
  The new overflow assertions must fail because the current adapters either
  dispatch the route, return a transport 431, or omit the 413 contract entry.

### Task 2: Implement Python and FastAPI ingress limits

**Files:**
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`

**Interfaces:** Keep `REQUEST_QUERY_TOO_LARGE` constants and error text stable.

- [x] **Step 1: Add the standard-library pre-routing check**

  In each API method entry (`do_GET`, `do_POST`, and `do_DELETE`), inspect the
  raw query portion and call `_send_error(..., 413, "REQUEST_QUERY_TOO_LARGE")`
  before route selection when an `/api/` request exceeds the byte budget.

- [x] **Step 2: Add the ASGI middleware**

  Add `_RequestQueryLimitMiddleware` next to `_RequestBodyLimitMiddleware`.
  For HTTP scopes whose path starts with `/api/`, reject
  `len(scope.get("query_string", b"")) > MAX_REQUEST_QUERY_BYTES` with a
  `JSONResponse` containing the stable error envelope, otherwise delegate.
  Register it in both `app` and `create_app`.

- [x] **Step 3: Run the focused Python tests**

  Run `.\venv\Scripts\python.exe -m unittest tests.test_main tests.test_main_fastapi_extended tests.test_api_contract` and verify all focused tests pass.

### Task 3: Implement Express ingress limit and transport envelope

**Files:**
- Modify: `frontend/server.js`
- Modify: `frontend/server.test.js`

**Interfaces:** Preserve `sendApiError` and all existing proxy handlers.

- [x] **Step 1: Add the raw-query middleware**

  Measure `Buffer.byteLength(req.originalUrl.slice(queryIndex + 1), "utf8")`
  for `/api/` paths before route handlers. Return the same 413 error when the
  result exceeds `MAX_REQUEST_QUERY_BYTES`.

- [x] **Step 2: Bound the Node header parser**

  Replace `app.listen` with `http.createServer({ maxHeaderSize: 64 * 1024 }, app)`
  and listen on the existing host and port. Keep startup logging and error
  handling unchanged.

- [x] **Step 3: Run the Express tests**

  Run `cd frontend; npm test -- --run server.test.js` and verify exact-limit
  and overflow requests return the expected status and body.

### Task 4: Synchronize contract and iteration evidence

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_206.md`

- [x] **Step 1: Declare query-limit responses**

  Add the existing `ErrorResponse` 413 response to the six documented
  query-bearing GET operations and leave parameter schemas unchanged.

- [x] **Step 2: Record implementation and evidence**

  Add Iteration 206 to the changelog and current-state docs, create the audit
  report with exact test counts, and retain only the newest ten audit reports.

### Task 5: Self-review and full verification

- [x] **Step 1: Review the diff**

  Check for duplicated byte accounting, parser access before the guard, route
  behavior changes outside `/api/`, and accidental edits to unrelated files.

- [x] **Step 2: Run verification**

  Run aggregate and discovery Python suites, focused API tests, Vitest,
  typecheck, build, Playwright, compileall, Ruff, required-services
  integration, ledger tests, and `git diff --check`. Repair failures and repeat
  the review and relevant checks.
