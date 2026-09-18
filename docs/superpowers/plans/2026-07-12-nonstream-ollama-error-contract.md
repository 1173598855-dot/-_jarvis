# Non-Streaming Ollama Error Contract Implementation Plan

> **For agentic workers:** Execute this plan inline under the active continuous-iteration instruction.

**Goal:** Declare `/api/ollama/chat` and make its non-streaming upstream failures one stable three-service ErrorResponse.

**Architecture:** Keep manager internals compatible, but map their error marker at each public adapter. Express uses a dedicated buffered chat proxy so only valid success JSON reaches the client and token store.

**Tech Stack:** Python standard library HTTPServer, FastAPI/Pydantic, Express, OpenAPI 3.1 JSON, and loopback unittest fixtures.

## Global Constraints

- No new dependency; preserve GET/POST SSE behavior and the existing 32 KiB/413 boundary.
- `POST /api/ollama/chat` is strictly non-streaming; `stream: true` is `400 INVALID_REQUEST`.
- Any upstream chat failure is `502 OLLAMA_UPSTREAM_ERROR` with the exact generic message `Ollama chat request failed`.
- Do not leak raw upstream text, process errors, or the dirty-worktree state.

---

### Task 1: Declare the missing non-streaming path

**Files:**

- Modify: `tests/test_api_contract.py`
- Modify: `contracts/core-api.openapi.json`

- [ ] **Step 1: Write a failing declaration test**

Require `POST /api/ollama/chat`, its `OllamaChatRequest` and `OllamaChatResponse` schemas, plus 400/413/502 ErrorResponse responses. Validate a representative successful body and `OLLAMA_UPSTREAM_ERROR` body.

- [ ] **Step 2: Run red**

Run: `./venv/Scripts/python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_nonstream_chat_contract_is_declared`

Expected: `KeyError` because the path is absent.

- [ ] **Step 3: Add OpenAPI 1.7.0 declarations**

Add the POST operation, request/response schemas, and all four response statuses.

- [ ] **Step 4: Run green**

Run the same command. Expected: PASS.

### Task 2: Reproduce and normalize all public adapters

**Files:**

- Modify: `tests/test_api_contract.py`
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `frontend/server.js`

- [ ] **Step 1: Write a failing three-service upstream-error test**

Add a fixture model `fixture-error` that responds with HTTP 500 and a raw error string. Send it to all three POST chat endpoints and require 502, `OLLAMA_UPSTREAM_ERROR`, and the generic message. Also validate successful chat bodies against `OllamaChatResponse` and require `stream: true` to produce 400 without an upstream call.

- [ ] **Step 2: Run red**

Run: `./venv/Scripts/python.exe -m unittest tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas`

Expected: Python HTTPServer returns 200/string error, FastAPI gives 500/HTTP_500, and Express forwards upstream failure.

- [ ] **Step 3: Implement minimal boundary adapters**

Force `stream=False` in Python, return the shared 400/502 error envelope, and replace Express's generic proxy use with a buffered `proxyOllamaChat` helper that parses only valid successful JSON and records tokens after that validation.

- [ ] **Step 4: Run green**

Run the focused contract test plus `./venv/Scripts/python.exe -m unittest tests.test_main tests.test_main_fastapi`; run `cd frontend; npm test -- --run server.test.js`. Expected: PASS.

### Task 3: Record Iteration 117

**Files:**

- Modify: `AGENTS.md`, `CHANGELOG.md`, `docs/reports/GITHUB_LEARNING_REPORT.md`, `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_117.md`
- Delete: `docs/reports/AUDIT_REPORT_107.md`

- [ ] **Step 1: Record research and public-error safety evidence**

Record Ollama (175,985 Stars, MIT) and Pydantic (28,257 Stars, MIT) as active unarchived candidates; document the no-dependency decision and raw-error non-disclosure.

- [ ] **Step 2: Run delivery gate and record exact counts**

Run aggregate/discovery Python suites, compileall, Vitest, Playwright, typecheck, build, and `git diff --check`; retain audits 108-117.
