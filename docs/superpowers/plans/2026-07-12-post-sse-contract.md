# POST SSE Contract Implementation Plan

> **For agentic workers:** Execute this plan inline. The active user instruction is a continuous development request, so do not pause for a handoff choice.

**Goal:** Declare and implement `POST /api/ollama/chat/stream` consistently across Express, Python HTTPServer, and FastAPI.

**Architecture:** Keep GET for URL-driven EventSource clients and introduce POST as a JSON-body alias. The OpenAPI document specifies both operations; each server reuses its existing stream generator and canonical SSE framing.

**Tech Stack:** Python standard library HTTPServer, FastAPI, Express, OpenAPI 3.1 JSON, unittest, Vitest, and the loopback Ollama fixture.

## Global Constraints

- Add no dependency and keep test networking on `127.0.0.1` with dynamic ports.
- POST input is a JSON object; invalid JSON is `400 INVALID_JSON` and non-object JSON is `400 INVALID_REQUEST`.
- Success emits canonical content frames and exactly one `data: [DONE]`; stream errors never emit that terminal marker.
- Preserve GET compatibility and do not stage, commit, delete, or overwrite unrelated dirty-worktree changes.

---

### Task 1: Declare POST SSE before implementation

**Files:**

- Modify: `tests/test_api_contract.py`
- Modify: `contracts/core-api.openapi.json`

**Interfaces:**

- Produces: an OpenAPI `post` operation for `/api/ollama/chat/stream` with JSON request and SSE/error responses.

- [x] **Step 1: Write the failing declaration test**

Add a test that obtains `contract["paths"]["/api/ollama/chat/stream"]["post"]`, requires an `application/json` request body and validates its `400` `ErrorResponse` and `200` `text/event-stream` declaration.

- [x] **Step 2: Run it red**

Run: `./venv/Scripts/python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_post_stream_contract_is_declared`

Expected: `KeyError: 'post'` because the contract currently declares only GET.

- [x] **Step 3: Add the contract operation**

Set the contract version to `1.5.0`. Add `post` beside `get`, with request fields `model` (`string`, `minLength: 1`) and `messages` (`array`), 200 SSE response referencing `SseContentFrame`/`SseErrorFrame`, and 400 `ErrorResponse`.

- [x] **Step 4: Run it green**

Run the same command. Expected: PASS.

### Task 2: Prove and implement three-service POST behavior

**Files:**

- Modify: `tests/test_api_contract.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi.py`
- Modify: `frontend/server.test.js`
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `frontend/server.js`

**Interfaces:**

- Consumes: `{ model: string, messages: array }` JSON.
- Produces: `200 text/event-stream` with `SseContentFrame` frames and terminal `[DONE]`, or a 400 ErrorResponse for malformed bodies.

- [x] **Step 1: Write failing integration and route tests**

Add `_post_sse_payloads(url, payload)` to the contract harness. Send the fixture payload to all three POST routes and assert 200, exactly one `[DONE]`, a canonical frame, and one `done: true` frame. Add Python route/validation tests and an Express test for non-object JSON input.

- [x] **Step 2: Run focused tests red**

Run: `./venv/Scripts/python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas tests.test_main tests.test_main_fastapi`

Run from `frontend`: `npm test -- --run server.test.js`

Expected: Python HTTPServer returns 404 and FastAPI 405 for POST stream; their route tests fail.

- [x] **Step 3: Write minimal adapters**

In `src/main.py`, add the POST route, decode the validated body, and route both methods through a helper that writes the existing canonical frames. In `src/main_fastapi.py`, make a helper returning the existing `StreamingResponse` and call it from both GET and POST endpoints. In Express, reject a non-object body with `sendApiError(res, 400, 'INVALID_REQUEST', 'Request body must be a JSON object')` before calling `streamOllamaChat`.

- [x] **Step 4: Run focused tests green**

Run the commands in Step 2. Expected: PASS.

### Task 3: Close Iteration 114

**Files:**

- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/GITHUB_LEARNING_REPORT.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_114.md`
- Delete: `docs/reports/AUDIT_REPORT_104.md`

- [x] **Step 1: Record the Phase 3 review and delivery evidence**

Record the 2026-07-12 metadata review: Schemathesis 3,452 stars/MIT, Spectral 3,151 stars/Apache-2.0, Prism 4,983 stars/Apache-2.0, and OpenAPI Specification 31,085 stars/Apache-2.0; all are active and unarchived. Keep the no-dependency decision because deterministic loopback tests cover the required path.

- [x] **Step 2: Run the delivery gate**

Run the Python aggregate and discovery suites, compileall, frontend tests, E2E, typecheck, build, and `git diff --check`. Record actual counts and retain only audit reports 105-114.
