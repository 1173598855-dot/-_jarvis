# Core API Contract Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the stable Core API contract for capability resources, memory and plugin mutations, SSE frames, and remaining public error envelopes across Express, Python HTTPServer, and FastAPI.

**Architecture:** Keep `contracts/core-api.openapi.json` as the machine-readable source of truth and extend the existing real-service harness in `tests/test_api_contract.py`. Express must be tested with `JARVIS_CORE_API_URL` pointing at a live Core service; FastAPI must use an isolated `AppState`; all temporary memory and subprocess resources are cleaned in `finally` blocks.

**Tech Stack:** OpenAPI 3.1 JSON, Python 3.10+ standard library `unittest`/`urllib`, FastAPI TestClient, Express 5, Vitest, local Ollama HTTP fixture.

## Global Constraints

- Add no runtime or development dependency.
- Bind all test services to `127.0.0.1` on dynamic ports.
- Preserve the existing `{ "error": { "code": string, "message": string } }` envelope.
- Do not make external Ollama or internet access a test prerequisite.
- Do not stage pre-existing overlapping worktree changes; commit only files whose staged diff is fully attributable to this plan.
- Each iteration updates `docs/reports/PROJECT_ANALYSIS.md`, `CHANGELOG.md`, `docs/reports/README.md`, and `docs/reports/AUDIT_REPORT_<N>.md`, retaining only the latest ten audit reports.

---

### Task 1: Iteration 101 Read-Only Capability Contracts

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `tests/test_api_contract.py`
- Modify: `docs/reports/GITHUB_LEARNING_REPORT.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_101.md`
- Delete: `docs/reports/AUDIT_REPORT_91.md`

**Interfaces:**
- Consumes: existing `_assert_json_shape(document, schema, value)` and live service harness.
- Produces: `PluginInfo`, `PluginListResponse`, `MemoryEntry`, `MemoryEntriesResponse`, `EventInfo`, and `EventListResponse` schemas; declared GET paths for plugins, memories, and events.

- [ ] **Step 1: Write failing contract declarations and live-response tests**

Add the three paths to `test_stable_shared_paths_are_declared`, add sample objects that exercise every array-item field, and include the paths in the live GET loop. Configure Express before launch:

```python
core_url = f"http://127.0.0.1:{http_server.server_port}"
express_env["JARVIS_CORE_API_URL"] = core_url

for path in ("/api/plugins", "/api/memory/entries", "/api/events"):
    operation = self.contract["paths"][path]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    for name, request in clients.items():
        status, body = request(path)
        self.assertEqual(status, 200, name)
        _assert_json_shape(self, self.contract, schema, body, name)
```

- [ ] **Step 2: Run the red test**

Run: `python -m unittest tests.test_api_contract.TestSharedApiContract.test_stable_shared_paths_are_declared tests.test_api_contract.TestSharedApiContract.test_all_implementations_match_stable_response_schemas`

Expected: FAIL because the three OpenAPI paths and schemas do not exist.

- [ ] **Step 3: Add the OpenAPI paths and schemas**

Declare 200 JSON responses and exact stable fields. `MemoryEntry.created_at` is a string, `tags` is a required string array, `access_count` is an integer with minimum 0, plugin permissions are strings, and event fields are strings. Add `tags` to both Python memory-list serializers so the runtime matches the existing frontend type. Increment contract version to `1.2.0`.

- [ ] **Step 4: Run focused and aggregate verification**

Run: `python -m unittest tests.test_api_contract`

Expected: all contract tests pass, including Express proxy responses.

Run: `python tests/run_all.py`

Expected: all canonical tests pass.

- [ ] **Step 5: Record Iteration 101**

Record the successful GitHub evaluation of Schemathesis (MIT), openapi-core (BSD-3-Clause), and Ajv (MIT), with the no-dependency decision. Update scores and the rolling report window, then verify:

Run: `python -m unittest tests.test_iteration_ledger tests.test_readme tests.test_docs_setup`

Expected: PASS with Iteration 101 and reports 92-101.

### Task 2: Iteration 102 Memory Lifecycle Contract

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `tests/test_api_contract.py`
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_102.md`
- Delete: `docs/reports/AUDIT_REPORT_92.md`

**Interfaces:**
- Consumes: `MemoryStore.store`, `MemoryStore.delete_probe`, Express Core proxy.
- Produces: `MemoryStoreRequest`, `MemoryStoreResponse`, `ProbeCleanupRequest`, `MemoryDeleteResponse`; `_delete_json(url, payload)` test helper.

- [ ] **Step 1: Write failing lifecycle tests**

Add `_delete_json` using `urllib.request.Request(method="DELETE")`. For each implementation, store a unique probe with `.test-local-integration-contract-<uuid>` title and cleanup token, assert the returned object matches `MemoryStoreResponse`, list entries and find its ID, delete it, and assert a repeated delete returns 404 `MEMORY_NOT_FOUND`.

```python
payload = {
    "type": "user",
    "title": f".test-local-integration-contract-{uuid.uuid4().hex}",
    "content": "contract probe",
    "tags": ["contract"],
    "probe_cleanup_token": cleanup_token,
}
```

- [ ] **Step 2: Run the red lifecycle test**

Run: `python -m unittest tests.test_api_contract.TestSharedApiContract.test_memory_lifecycle_matches_contract`

Expected: FAIL because mutation paths and schemas are absent or an implementation response differs.

- [ ] **Step 3: Implement the minimal lifecycle contract**

Declare POST store and DELETE probe paths, including path parameters with `enum` values for `user`, `feedback`, `project`, and `reference`. Preserve `MEMORY_NOT_FOUND` and the successful response fields `success`, `id`, `type`, and `path` where applicable. Increment version to `1.3.0`.

- [ ] **Step 4: Verify lifecycle cleanup**

Run: `python -m unittest tests.test_api_contract tests.test_context_compressor tests.test_main tests.test_main_fastapi`

Expected: PASS; no `.test-local-integration-contract-*` entry remains in `.auto-memory` or temporary directories.

- [ ] **Step 5: Record Iteration 102**

Update the analysis and rolling ledger to reports 93-102. Run `python tests/run_all.py`; expected PASS.

### Task 3: Iteration 103 Plugin Action Contract and Stable Errors

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `tests/test_api_contract.py`
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_103.md`
- Delete: `docs/reports/AUDIT_REPORT_93.md`

**Interfaces:**
- Consumes: repository plugin `event-logger`, `PluginManager.discover/load/enable/disable`.
- Produces: `PluginActionRequest`, `PluginLoadResponse`, `PluginToggleResponse`; codes `MISSING_PLUGIN_ID` and `PLUGIN_NOT_FOUND`.

- [ ] **Step 1: Write failing handler and cross-service tests**

Assert all three actions return 400 for `{ "plugin_id": "" }` with `MISSING_PLUGIN_ID`; load of `missing-contract-plugin` returns 404 `PLUGIN_NOT_FOUND`; load/enable/disable of `event-logger` matches the declared success schemas.

- [ ] **Step 2: Run the red plugin tests**

Run: `python -m unittest tests.test_main tests.test_main_fastapi tests.test_api_contract`

Expected: FAIL because Python HTTPServer currently returns generic `HTTP_400`, FastAPI validation can return 422/default detail, and action paths are undeclared.

- [ ] **Step 3: Implement shared plugin validation**

In Python HTTPServer, check `plugin_id` before manager calls:

```python
if not plugin_id:
    self._send_error(
        "Missing plugin_id parameter",
        400,
        "MISSING_PLUGIN_ID",
    )
    return
```

In FastAPI, use the same stable detail object:

```python
if not request.plugin_id:
    raise HTTPException(
        status_code=400,
        detail={
            "code": "MISSING_PLUGIN_ID",
            "message": "Missing plugin_id parameter",
        },
    )
```

Return 404 `PLUGIN_NOT_FOUND` when discovery has no matching manifest. Keep successful response shapes unchanged. Declare all action paths and increment contract version to `1.4.0`.

- [ ] **Step 4: Verify plugin behavior and security boundary**

Run: `python -m unittest tests.test_plugin_sdk tests.test_plugin_installation tests.test_main tests.test_main_fastapi tests.test_api_contract`

Expected: PASS; the test only loads the repository-owned `event-logger` manifest and adds no external code or permission.

- [ ] **Step 5: Record Iteration 103**

Update the analysis and rolling ledger to reports 94-103. Run `python tests/run_all.py`; expected PASS.

### Task 4: Iteration 104 Canonical SSE Frames

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `frontend/server.js`
- Modify: `frontend/server.test.js`
- Modify: `src/main.py`
- Modify: `src/main_fastapi.py`
- Modify: `tests/test_api_contract.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_main_fastapi.py`
- Modify: `frontend/src/services/chat-stream.ts`
- Modify: `frontend/src/tests/chat-stream.test.ts`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_104.md`
- Delete: `docs/reports/AUDIT_REPORT_94.md`

**Interfaces:**
- Consumes: Ollama native frames with `message.content`, `done`, and token counters.
- Produces: content frame `{model, content, done}`, error frame `{error:{code,message}}`, one terminal `data: [DONE]` only on successful completion.

- [ ] **Step 1: Write failing SSE parser and live stream tests**

Add a helper that reads `text/event-stream`, extracts every `data:` payload, and asserts the successful sequence contains at least one schema-valid content frame, exactly one frame with `done: true`, and exactly one final `[DONE]`. Add an upstream 500 fixture case that asserts one `OLLAMA_STREAM_ERROR` frame and no `[DONE]`.

- [ ] **Step 2: Run red backend and frontend tests**

Run: `python -m unittest tests.test_api_contract tests.test_main tests.test_main_fastapi`

Run from `frontend/`: `npx vitest run server.test.js src/tests/chat-stream.test.ts`

Expected: FAIL because Express forwards native Ollama frames and string errors, while backend errors can append or omit inconsistent termination markers.

- [ ] **Step 3: Normalize streaming adapters**

Normalize upstream frames before writing:

```javascript
const content = frame.message?.content ?? frame.content ?? '';
const normalized = { model: frame.model || payload.model, content, done: frame.done === true };
```

Emit errors as `{ error: { code: 'OLLAMA_STREAM_ERROR', message } }`; do not emit `[DONE]` after an error. Apply the same error frame in both Python generators. Declare `text/event-stream` response content and increment version to `1.5.0`.

- [ ] **Step 4: Verify SSE and token accounting**

Run: `python -m unittest tests.test_api_contract tests.test_ollama_manager tests.test_main tests.test_main_fastapi`

Run from `frontend/`: `npm test -- --run`

Expected: PASS; native token counts are still recorded once and the browser parser accepts canonical frames.

- [ ] **Step 5: Record Iteration 104**

Update the analysis and rolling ledger to reports 95-104. Run `python tests/run_all.py`; expected PASS.

### Task 5: Iteration 105 Public Error Envelope Gate

**Files:**
- Modify: `contracts/core-api.openapi.json`
- Modify: `tests/test_api_contract.py`
- Modify: `src/main_fastapi.py`
- Modify: `frontend/server.js`
- Modify: `frontend/server.test.js`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/services/jarvis-api.ts`
- Modify: `frontend/src/tests/jarvis-api.test.ts`
- Modify: `CHANGELOG.md`
- Modify: `docs/reports/PROJECT_ANALYSIS.md`
- Modify: `docs/reports/README.md`
- Create: `docs/reports/AUDIT_REPORT_105.md`
- Delete: `docs/reports/AUDIT_REPORT_95.md`

**Interfaces:**
- Consumes: `sendApiError`, FastAPI `RequestValidationError`, OpenAPI response declarations.
- Produces: `INVALID_REQUEST`, `TERMINAL_EXECUTION_FAILED`, `GIT_COMMAND_FAILED`, `OLLAMA_UNAVAILABLE`, and `FRONTEND_NOT_BUILT`; optional `error.details` schema.

- [ ] **Step 1: Write failing error-shape tests**

Test malformed FastAPI request bodies, a mocked terminal subprocess failure, mocked Git failure, missing frontend build, Core not configured, Core unavailable, and invalid Core JSON. Every response must pass `ErrorResponse` and include a stable code and non-empty message. Add a contract document test that every declared 4xx/5xx JSON response references `ErrorResponse`.

- [ ] **Step 2: Run the red tests**

Run: `python -m unittest tests.test_api_contract tests.test_main_fastapi`

Run from `frontend/`: `npx vitest run server.test.js src/tests/jarvis-api.test.ts`

Expected: FAIL on remaining string `error` payloads and FastAPI's default validation body.

- [ ] **Step 3: Normalize public error writers**

Register a `RequestValidationError` handler that returns 400 `INVALID_REQUEST` with serialized errors in `details`. Replace every Express `res.status(...).json({ error: err.message })` and string fallback with `sendApiError`. Extend `ErrorResponse` with optional `details` and increment contract version to `2.0.0`.

- [ ] **Step 4: Run the complete verification baseline**

Run: `python tests/run_all.py`

Run: `python -m unittest discover -s tests -p "test_*.py"`

Run: `python -m compileall -q src tests scripts`

Run from `frontend/`: `npm test -- --run`

Run from `frontend/`: `npm run test:e2e`

Run from `frontend/`: `npm run typecheck`

Run from `frontend/`: `npm run build`

Expected: every command passes; Playwright may retain only its documented desktop-condition skip.

- [ ] **Step 5: Record Iteration 105 and review the accumulated diff**

Update scores and residual risks from fresh results, retain reports 96-105, run `git diff --check`, and inspect `git status --short`. Do not stage any pre-existing overlapping worktree change. The goal is complete only when the full verification baseline and ledger guards pass.
