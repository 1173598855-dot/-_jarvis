# Shared Request-Body Limit Implementation Plan

> **For agentic workers:** Execute this plan inline. The active user instruction requires continuous iteration, so do not pause for a handoff choice.

**Goal:** Make the 32 KiB JSON body limit and its 413 error envelope consistent across all three API services.

**Architecture:** A shared public error code describes the limit. Python HTTPServer checks `Content-Length` before reading, FastAPI checks it in outer middleware before request parsing, and Express translates its parser error. The existing loopback contract harness proves all three results.

**Tech Stack:** Python standard library HTTPServer, FastAPI/Starlette ASGI, Express, OpenAPI 3.1 JSON, and unittest.

## Global Constraints

- The limit is exactly 32 KiB (`32768` bytes), with no new dependency.
- Oversized JSON is `413 REQUEST_BODY_TOO_LARGE` with a generic message and must not invoke Ollama.
- Keep existing 400 malformed/non-object body behavior and do not stage, commit, or disturb unrelated dirty changes.

---

### Task 1: Declare the error before implementation

**Files:**

- Modify: `tests/test_api_contract.py`
- Modify: `contracts/core-api.openapi.json`

- [x] **Step 1: Write a failing 413 declaration test**

Require the POST stream operation to expose a `413` response using `ErrorResponse`, then validate `{ "error": { "code": "REQUEST_BODY_TOO_LARGE", "message": "Request body exceeds the 32 KiB limit" } }` against it.

- [x] **Step 2: Run red**

Run: `./venv/Scripts/python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_post_stream_body_limit_is_declared`

Expected: `KeyError: '413'`.

- [x] **Step 3: Add the OpenAPI response**

Advance `info.version` to `1.6.0` and add 413 ErrorResponse to `POST /api/ollama/chat/stream`.

- [x] **Step 4: Run green**

Run the same command. Expected: PASS.

### Task 2: Reproduce and close the three-service boundary

**Files:**

- Modify: `tests/test_api_contract.py`
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `frontend/server.js`

- [x] **Step 1: Write the failing live test**

Create a UTF-8 JSON payload over 32 KiB and send it to the POST stream endpoint for Python HTTPServer, FastAPI, and Express. Require 413 and the shared error schema/code.

- [x] **Step 2: Run red**

Run: `./venv/Scripts/python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas`

Expected: at least Python HTTPServer or FastAPI accepts the oversized payload instead of returning 413.

- [x] **Step 3: Implement the limit**

Use `32768` bytes in all adapters. In Python HTTPServer, raise a typed request error before `rfile.read`; in FastAPI, immediately return a JSON 413 if the declared content length is over the limit; in Express, map `entity.too.large` in the existing terminal error middleware.

- [x] **Step 4: Run green**

Run the focused test and `./venv/Scripts/python.exe -m unittest tests.test_main tests.test_main_fastapi`. Expected: PASS.

### Task 3: Record Iteration 115

**Files:**

- Modify: `AGENTS.md`, `CHANGELOG.md`, `docs/reports/GITHUB_LEARNING_REPORT.md`, `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_115.md`
- Delete: `docs/reports/AUDIT_REPORT_105.md`

- [x] **Step 1: Record Phase 3 and security evidence**

Record FastAPI (100,404 Stars, MIT) and Starlette (12,470 Stars, BSD-3-Clause) as active, unarchived references. State the no-dependency decision and document the byte-based 32 KiB boundary.

- [x] **Step 2: Run delivery gate and record actual results**

Run the aggregate/discovery Python suites, compileall, Vitest, Playwright, typecheck, build, and `git diff --check`, then record exact counts and retain audits 106-115.
